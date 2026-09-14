"""Direct Local Bridge to running Google Antigravity Background Sidecar.

Connects ComfyUI directly to the user's active Antigravity session (language_server.exe)
without needing any Gemini or OpenAI API keys, Google Cloud billing, or external proxies.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

import httpx
import psutil

logger = logging.getLogger("ComfyUI-Antigravity-Agent.Bridge")

# Supported models available on user's active Antigravity subscription
SUPPORTED_MODELS = {
    "gemini-3.8-flash-high": {
        "name": "Gemini 3.8 Flash (High Thinking)",
        "enum": "MODEL_PLACEHOLDER_M318",
        "owned_by": "google",
    },
    "gemini-3.7-flash-high": {
        "name": "Gemini 3.7 Flash (High Thinking)",
        "enum": "MODEL_PLACEHOLDER_M298",
        "owned_by": "google",
    },
    "claude-sonnet-4-6": {
        "name": "Claude Sonnet 4.6 (Thinking)",
        "enum": "MODEL_PLACEHOLDER_M18",
        "owned_by": "anthropic",
    },
}

DEFAULT_MODEL_KEY = "gemini-3.8-flash-high"


class AntigravityLocalBridge:
    """Discovers and communicates with the running Antigravity language_server process."""

    def __init__(self):
        self._cached_port: Optional[int] = None
        self._cached_token: Optional[str] = None
        self._cached_pid: Optional[int] = None
        self.active_model_key: str = DEFAULT_MODEL_KEY

    def discover_session(self) -> Optional[Tuple[int, int, str]]:
        """Scans running processes for Antigravity's language_server.

        Returns (pid, port, csrf_token) or None if not running.
        """
        sidecar_proc = None
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                name = (proc.info["name"] or "").lower()
                if "language_server" in name:
                    sidecar_proc = proc
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not sidecar_proc:
            return None

        pid = sidecar_proc.pid
        cmdline_list = sidecar_proc.info.get("cmdline") or []
        cmdline_str = " ".join(cmdline_list)

        token_match = re.search(r"--csrf_token\s+([a-f0-9-]+)", cmdline_str)
        if not token_match:
            return None
        csrf_token = token_match.group(1)

        # Collect listening TCP ports
        candidate_ports: List[int] = []
        try:
            for conn in sidecar_proc.net_connections(kind="inet"):
                if conn.status == "LISTEN":
                    candidate_ports.append(conn.laddr.port)
        except Exception as e:
            logger.warning(f"Failed to inspect net_connections: {e}")

        if not candidate_ports:
            return None

        # Probe candidate ports for ConnectRPC GetStatus response
        headers = {
            "content-type": "application/json",
            "connect-protocol-version": "1",
            "x-codeium-csrf-token": csrf_token,
        }

        active_port = None
        for port in candidate_ports:
            try:
                with httpx.Client(http2=True, verify=False, timeout=1.5) as client:
                    resp = client.post(
                        f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetStatus",
                        headers=headers,
                        json={},
                    )
                    if resp.status_code == 200:
                        active_port = port
                        break
            except Exception:
                continue

        if not active_port:
            return None

        self._cached_pid = pid
        self._cached_port = active_port
        self._cached_token = csrf_token
        return (pid, active_port, csrf_token)

    def get_status(self) -> Dict[str, Any]:
        """Returns the current bridge status and active Antigravity session metadata."""
        session = self.discover_session()
        if session:
            pid, port, _ = session
            return {
                "running": True,
                "pid": pid,
                "port": port,
                "model": self.active_model_key,
                "model_info": SUPPORTED_MODELS.get(self.active_model_key, {}),
                "available_models": {k: v["name"] for k, v in SUPPORTED_MODELS.items()},
                "auth": "Antigravity Subscription (Local Bridge - Zero API Key)",
            }
        return {
            "running": False,
            "pid": None,
            "port": None,
            "model": self.active_model_key,
            "error": "Antigravity desktop app is not detected running in background.",
        }

    def format_prompt_with_tools(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools_schema: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Constructs a structured prompt containing instructions, tools, and conversation history."""
        parts = [f"[System Instructions]\n{system_prompt}\n"]

        if tools_schema:
            parts.append("# Available Tools")
            parts.append("You have access to tools that can directly modify the ComfyUI canvas.")
            parts.append("Before executing any tools, state your reasoning inside <thought>...</thought> tags.")
            parts.append("When you execute tools, emit them strictly in this format:")
            parts.append('<tool_call>{"name": "tool_name", "arguments": {"param": "value"}}</tool_call>\n')
            parts.append("Available tools:")
            for tool in tools_schema:
                t_name = tool.get("name", "")
                t_desc = tool.get("description", "")
                t_params = json.dumps(tool.get("parameters", {}), indent=2)
                parts.append(f"## {t_name}\nDescription: {t_desc}\nParameters:\n{t_params}\n")
            parts.append("CRITICAL: When the user asks you to build, change, wire, or execute workflows, use your tools.")
            parts.append("Always place planning in <thought>...</thought>, then emit the necessary <tool_call>s.\n")

        parts.append("# Conversation History")
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                parts.append(f"[User]\n{content}\n")
            elif role == "assistant":
                parts.append(f"[Assistant]\n{content}\n")
            elif role == "tool":
                parts.append(f"[Tool Result: {msg.get('name', 'tool')}]\n{content}\n")

        parts.append("[Assistant]\n")
        return "\n".join(parts)

    async def query_model(
        self,
        prompt: str,
        model_key: Optional[str] = None,
        timeout: float = 60.0,
    ) -> str:
        """Sends inference request to the Antigravity language_server."""
        session = self.discover_session()
        if not session:
            raise RuntimeError(
                "Antigravity desktop app is not running. Please start Antigravity to use your subscription."
            )

        _, port, token = session
        target_model = model_key or self.active_model_key
        model_entry = SUPPORTED_MODELS.get(target_model, SUPPORTED_MODELS[DEFAULT_MODEL_KEY])
        model_enum = model_entry["enum"]

        headers = {
            "content-type": "application/json",
            "connect-protocol-version": "1",
            "x-codeium-csrf-token": token,
        }

        payload = {
            "prompt": prompt,
            "model": model_enum,
        }

        async with httpx.AsyncClient(http2=True, verify=False, timeout=timeout) as client:
            resp = await client.post(
                f"https://127.0.0.1:{port}/exa.language_server_pb.LanguageServerService/GetModelResponse",
                headers=headers,
                json=payload,
            )

            if resp.status_code != 200:
                raise RuntimeError(f"Antigravity sidecar returned HTTP {resp.status_code}: {resp.text}")

            data = resp.json()
            return data.get("response", "")


bridge = AntigravityLocalBridge()
