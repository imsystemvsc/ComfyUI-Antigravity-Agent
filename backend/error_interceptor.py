"""Execution Error Interceptor.

Hooks into ComfyUI's PromptServer event stream to capture runtime execution errors
(OOMs, missing tensors, dimension errors) and make them available to Antigravity for diagnosis and self-healing.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("ComfyUI-Antigravity-Agent.ErrorInterceptor")

_LAST_EXECUTION_ERROR: Optional[Dict[str, Any]] = None


def get_last_error() -> Optional[Dict[str, Any]]:
    """Returns the most recent execution error payload."""
    return _LAST_EXECUTION_ERROR


def clear_last_error():
    """Clears the cached error."""
    global _LAST_EXECUTION_ERROR
    _LAST_EXECUTION_ERROR = None


def init_error_interceptor(prompt_server: Any):
    """Wraps PromptServer.send_sync to intercept execution_error messages."""
    global _LAST_EXECUTION_ERROR
    
    if not hasattr(prompt_server, "send_sync"):
        return

    original_send_sync = prompt_server.send_sync

    def intercepted_send_sync(event: str, data: Any, sid: Optional[str] = None):
        global _LAST_EXECUTION_ERROR
        if event == "execution_error":
            logger.warning(f"[Antigravity] Intercepted ComfyUI execution error: {data.get('exception_type')}")
            _LAST_EXECUTION_ERROR = {
                "node_id": data.get("node_id"),
                "node_type": data.get("node_type"),
                "exception_type": data.get("exception_type"),
                "exception_message": data.get("exception_message"),
                "traceback": data.get("traceback", []),
                "timestamp": data.get("timestamp"),
            }
        elif event == "execution_success":
            _LAST_EXECUTION_ERROR = None

        return original_send_sync(event, data, sid=sid)

    prompt_server.send_sync = intercepted_send_sync
    logger.info("[Antigravity] Execution error interceptor active.")
