"""ComfyUI-Antigravity-Agent Custom Node Entrypoint.

Registers custom server routes, WebSocket endpoints, and the frontend web directory.
"""

import sys
import logging
from pathlib import Path

logger = logging.getLogger("ComfyUI-Antigravity-Agent")

# Expose web directory for ComfyUI frontend extension loader
WEB_DIRECTORY = "./web"

# No custom execution canvas nodes needed directly - agent controls existing nodes
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

try:
    import server
    from .backend.server import init_routes
    from .backend.error_interceptor import init_error_interceptor

    prompt_server = server.PromptServer.instance
    init_routes(prompt_server.app)
    init_error_interceptor(prompt_server)
    logger.info("[ComfyUI-Antigravity-Agent] Routes and Error Interceptor registered successfully.")
except Exception as e:
    logger.error(f"[ComfyUI-Antigravity-Agent] Initialization warning: {e}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
