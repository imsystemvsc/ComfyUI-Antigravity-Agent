"""Antigravity Agent Lifecycle Manager.

Connects to the local Google Antigravity background sidecar with zero API keys.
Streams thoughts, parses and executes canvas tool calls, and streams response tokens to ComfyUI.
"""

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional

from .antigravity_bridge import bridge

logger = logging.getLogger("ComfyUI-Antigravity-Agent.Agent")

SYSTEM_PROMPT = """You are ComfyUI-Antigravity-Agent, an expert workflow engineer and assistant running directly via Antigravity inside ComfyUI.
You have FULL AUTHORITY to construct, inspect, modify, rewire, and execute ComfyUI workflows.

Available capabilities:
1. `apply_graph_patch`: Add nodes, remove nodes, change widget values, and wire links in a single atomic patch.
2. `get_current_graph`: Retrieve full or outline state of the active canvas.
3. `resolve_model_pipeline`: Discover available models (Flux-2 Klein, Qwen GGUF, SDXL, Wan2.1) and recommend node pairings.
4. `queue_workflow`: Trigger immediate workflow generation.
5. `get_last_execution_error`: Retrieve traceback if an execution failed.

Rules:
- When asked to create, adjust, or wire workflows, plan your changes in <thought> tags, then emit <tool_call> tags.
- For Flux-2 Klein, pair with Qwen text encoder and compatible VAE.
- Keep explanations clear, technical, and concise.
"""


class AntigravityAgentRunner:
    """Manages conversational session and tool loop with the local Antigravity sidecar."""

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
        # 1. Verify Antigravity sidecar session
        status = bridge.get_status()
        if not status.get("running"):
            err_msg = (
                "⚠️ **Antigravity Background Process Not Found**\n\n"
                "Please make sure Google Antigravity is open and running on your PC. "
                "The ComfyUI agent connects directly to your active Antigravity session with zero API keys."
            )
            await on_token(err_msg)
            return err_msg

        # 2. Append user message to history
        self.history.append({"role": "user", "content": user_message})

        tools_schema = self.tool_dispatcher.get_tool_definitions()
        max_turns = 5
        full_reply_accum: List[str] = []

        for turn_idx in range(max_turns):
            # Construct structured prompt
            prompt = bridge.format_prompt_with_tools(
                system_prompt=SYSTEM_PROMPT,
                messages=self.history,
                tools_schema=tools_schema,
            )

            try:
                raw_response = await bridge.query_model(prompt)
            except Exception as e:
                err_msg = f"❌ Antigravity Error: {str(e)}"
                logger.error(f"[Antigravity] Inference failure: {e}", exc_info=True)
                await on_token(err_msg)
                return err_msg

            if not raw_response or not raw_response.strip():
                err_msg = "⚠️ Received empty response from Antigravity."
                await on_token(err_msg)
                return err_msg

            # Parse <thought> blocks
            thought_matches = re.findall(r"<thought>(.*?)</thought>", raw_response, flags=re.DOTALL)
            for t in thought_matches:
                thought_clean = t.strip()
                if thought_clean:
                    await on_thought(thought_clean)

            # Parse <tool_call> blocks
            tool_calls = []
            tool_matches = re.findall(r"<tool_call>(.*?)</tool_call>", raw_response, flags=re.DOTALL)
            for tm in tool_matches:
                try:
                    call_json = json.loads(tm.strip())
                    if "name" in call_json:
                        tool_calls.append(call_json)
                except Exception as ex:
                    logger.warning(f"Could not parse tool call JSON '{tm}': {ex}")

            # Extract clean assistant conversational text (strip thought and tool tags)
            clean_text = re.sub(r"<thought>.*?</thought>", "", raw_response, flags=re.DOTALL)
            clean_text = re.sub(r"<tool_call>.*?</tool_call>", "", clean_text, flags=re.DOTALL).strip()

            if tool_calls:
                # Record assistant turn with tool calls
                self.history.append({
                    "role": "assistant",
                    "content": raw_response,
                })

                # Execute tool calls
                for call in tool_calls:
                    t_name = call.get("name", "")
                    t_args = call.get("arguments", {})
                    await on_action(t_name, t_args)
                    await on_thought(f"Executing `{t_name}` on canvas...")

                    try:
                        dispatcher_fn = getattr(self.tool_dispatcher, "execute_tool", None) or getattr(self.tool_dispatcher, "dispatch", None)
                        if dispatcher_fn:
                            result = await dispatcher_fn(t_name, t_args)
                        else:
                            result = {"error": "Tool dispatcher has neither execute_tool nor dispatch"}
                    except Exception as ex:
                        result = {"error": str(ex)}

                    # Append tool result to history for next model turn
                    self.history.append({
                        "role": "tool",
                        "name": t_name,
                        "content": json.dumps(result),
                    })

                # Continue next turn so model can inspect tool results
                continue

            # No tool calls: final text response
            self.history.append({"role": "assistant", "content": clean_text})
            full_reply_accum.append(clean_text)


            # Stream response smoothly by tokens/words
            words = clean_text.split(" ")
            for i, word in enumerate(words):
                prefix = "" if i == 0 else " "
                await on_token(prefix + word)
                await asyncio.sleep(0.015)

            break

        return "".join(full_reply_accum)
