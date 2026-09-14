"""Antigravity Agent Lifecycle Manager.

Spawns and manages the google.antigravity Agent using local authentication and runtime credentials.
Streams reasoning and response tokens, and drives the tool-calling loop against ComfyUI tools.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger("ComfyUI-Antigravity-Agent.Agent")

SYSTEM_PROMPT = """You are ComfyUI-Antigravity-Agent, an expert pair-programmer and workflow engineer embedded inside ComfyUI.
You have FULL AUTHORITY to construct, inspect, modify, rewire, and execute ComfyUI workflows.

Guidelines:
1. When asked to create or change workflows, prefer using `apply_graph_patch` to execute modifications in a single batched turn.
2. If building from scratch, choose appropriate model loaders (e.g. UnetLoaderGGUF for .gguf, CheckpointLoaderSimple for merged checkpoints) and pair compatible VAE and CLIP encoders using `resolve_model_pipeline`.
3. To keep token consumption minimal, query the canvas via `get_current_graph` only when you need to inspect existing connections.
4. Auto-arrange new nodes left-to-right (Checkpoints/Encoders -> Samplers/Conditioning -> Decoders/Outputs).
5. If the user asks you to generate or test an image, invoke `queue_workflow` once the graph is ready.
6. If an execution fails, use `get_last_execution_error` to diagnose the traceback and apply a targeted fix.
"""


class AntigravityAgentRunner:
    """Manages conversational session and tool loop with the local google-antigravity runtime."""

    def __init__(self, tool_dispatcher: Any):
        self.tool_dispatcher = tool_dispatcher
        self.history: List[Dict[str, Any]] = []

    async def chat_stream(
        self,
        user_message: str,
        on_token: Callable[[str], Any],
        on_thought: Callable[[str], Any],
        on_action: Callable[[str, Dict[str, Any]], Any],
    ) -> str:
        """Runs an interactive agent turn, streaming tokens, thoughts, and executing tool calls."""
        try:
            from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
        except ImportError:
            error_msg = "Error: `google-antigravity` package is not installed. Please run `pip install google-antigravity` in your ComfyUI environment."
            await on_token(error_msg)
            return error_msg

        # Load config for api_key or model preferences
        api_key = os.environ.get("GEMINI_API_KEY")
        config_path = Path(__file__).resolve().parents[1] / "config.json"
        if not api_key and config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg_data = json.load(f)
                    api_key = cfg_data.get("api_key") or None
            except Exception:
                pass

        if not api_key:
            err_msg = "A Gemini API Key is required. Please obtain a free key at https://aistudio.google.com and enter it in the Antigravity settings or set the GEMINI_API_KEY environment variable."
            await on_token(err_msg)
            return err_msg

        config = LocalAgentConfig(
            system_instructions=SYSTEM_PROMPT,
            capabilities=CapabilitiesConfig(),
            api_key=api_key,
        )

        full_reply = []
        
        try:
            async with Agent(config) as agent:
                # Append user prompt
                self.history.append({"role": "user", "content": user_message})

                # Register tools
                tools_schema = self.tool_dispatcher.get_tool_definitions()

                response = await agent.chat(user_message, tools=tools_schema)

                # Stream thoughts if available
                if hasattr(response, "thoughts"):
                    async for thought in response.thoughts:
                        await on_thought(thought)

                # Process streamed tokens
                async for token in response:
                    full_reply.append(token)
                    await on_token(token)

                # Process any emitted tool calls
                if hasattr(response, "tool_calls"):
                    async for call in response.tool_calls:
                        tool_name = getattr(call, "name", "")
                        tool_args = getattr(call, "args", {})
                        await on_action(tool_name, tool_args)

                        # Execute the tool
                        result = await self.tool_dispatcher.execute_tool(tool_name, tool_args)

                        # Send tool result back to agent if supported
                        if hasattr(agent, "send_tool_result"):
                            followup = await agent.send_tool_result(call.id, result)
                            async for token in followup:
                                full_reply.append(token)
                                await on_token(token)

            final_text = "".join(full_reply)
            self.history.append({"role": "assistant", "content": final_text})
            return final_text

        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            err_notice = f"\n[Agent Error]: {str(e)}"
            await on_token(err_notice)
            return err_notice
