"""Server & WebSocket RPC Router.

Provides aiohttp WebSocket routing (/antigravity/ws) and REST endpoints for
streaming agent conversation, bi-directional canvas execution RPC, and template management.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web

from .agent import AntigravityAgentRunner
from .error_interceptor import get_last_error
from .model_scanner import ModelScanner
from .template_manager import TemplateManager
from .tools import AntigravityToolDispatcher

logger = logging.getLogger("ComfyUI-Antigravity-Agent.Server")


class AntigravitySessionManager:
    """Coordinates connected browser WebSocket sessions, pending RPC actions, and agent workers."""

    def __init__(self):
        self.active_ws: Optional[web.WebSocketResponse] = None
        self.pending_canvas_requests: Dict[str, asyncio.Future] = {}
        self.scanner = ModelScanner()
        self.template_mgr = TemplateManager()
        self.tool_dispatcher = AntigravityToolDispatcher(
            ws_action_sender=self.request_canvas_action,
            scanner=self.scanner,
            template_mgr=self.template_mgr,
            error_fn=get_last_error,
        )
        self.agent_runner = AntigravityAgentRunner(self.tool_dispatcher)

    async def request_canvas_action(self, action_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sends an RPC request to the frontend canvas executor and awaits response."""
        if not self.active_ws or self.active_ws.closed:
            return {"error": "No active ComfyUI browser tab connected via WebSocket"}

        request_id = f"req_{int(asyncio.get_event_loop().time() * 1000)}"
        future = asyncio.get_event_loop().create_future()
        self.pending_canvas_requests[request_id] = future

        await self.active_ws.send_json({
            "type": "canvas_action",
            "request_id": request_id,
            "action": action_type,
            "params": params,
        })

        try:
            # Wait up to 30s for the browser to execute the canvas action
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            return {"error": f"Timed out waiting for canvas execution of '{action_type}'"}
        finally:
            self.pending_canvas_requests.pop(request_id, None)

    def handle_canvas_response(self, request_id: str, result: Dict[str, Any]):
        """Fulfills the pending future when browser sends back an action result."""
        future = self.pending_canvas_requests.get(request_id)
        if future and not future.done():
            future.set_result(result)


manager = AntigravitySessionManager()


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Handles WebSocket connection from the ComfyUI chat window."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    manager.active_ws = ws
    logger.info("[Antigravity] Browser chat client connected.")

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type == "user_prompt":
                    user_text = data.get("prompt", "")

                    async def on_token(token: str):
                        await ws.send_json({"type": "token_delta", "delta": token})

                    async def on_thought(thought: str):
                        await ws.send_json({"type": "thought_delta", "thought": thought})

                    async def on_action(name: str, args: Dict[str, Any]):
                        await ws.send_json({"type": "action_notice", "tool": name, "args": args})

                    # Run agent turn in background task to avoid blocking WS receiver
                    asyncio.create_task(
                        manager.agent_runner.chat_stream(
                            user_message=user_text,
                            on_token=on_token,
                            on_thought=on_thought,
                            on_action=on_action,
                        )
                    )

                elif msg_type == "canvas_action_result":
                    req_id = data.get("request_id")
                    result = data.get("result", {})
                    manager.handle_canvas_response(req_id, result)

                elif msg_type == "ping":
                    await ws.send_json({"type": "pong"})

            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"[Antigravity] WebSocket closed with error: {ws.exception()}")
    finally:
        if manager.active_ws is ws:
            manager.active_ws = None
        logger.info("[Antigravity] Browser chat client disconnected.")

    return ws


async def list_templates_endpoint(request: web.Request) -> web.Response:
    return web.json_response({"templates": manager.template_mgr.list_templates()})


async def save_template_endpoint(request: web.Request) -> web.Response:
    data = await request.json()
    result = manager.template_mgr.save_extracted_template(
        name=data.get("name", "untitled_template"),
        description=data.get("description", ""),
        selected_nodes=data.get("nodes", []),
        links=data.get("links", []),
    )
    return web.json_response({"status": "ok", "template": result})


async def list_models_endpoint(request: web.Request) -> web.Response:
    scan = manager.scanner.scan_all()
    return web.json_response(scan)


def init_routes(target: Any):
    """Registers endpoints onto ComfyUI's routes table or aiohttp application."""
    if hasattr(target, "get") and callable(target.get):
        # Target is PromptServer.instance.routes (RouteTableDef)
        target.get("/antigravity/ws")(ws_handler)
        target.get("/antigravity/templates")(list_templates_endpoint)
        target.post("/antigravity/save_template")(save_template_endpoint)
        target.get("/antigravity/models")(list_models_endpoint)
    elif hasattr(target, "router"):
        # Target is PromptServer.instance.app (web.Application)
        target.router.add_get("/antigravity/ws", ws_handler)
        target.router.add_get("/antigravity/templates", list_templates_endpoint)
        target.router.add_post("/antigravity/save_template", save_template_endpoint)
        target.router.add_get("/antigravity/models", list_models_endpoint)

