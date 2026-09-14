"""Tool definitions for Antigravity Agent.

Exposes declarative tools to the agent:
- Macro graph patching (creates, connects, updates, deletes)
- Compact graph retrieval
- Node discovery & schema inspection
- Model & companion resolution
- Subgraph template splicing
- Execution queuing and error diagnosis
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ComfyUI-Antigravity-Agent.Tools")


class AntigravityToolDispatcher:
    """Dispatches tool calls to either the backend scanner or the browser canvas executor via WebSocket."""

    def __init__(self, ws_action_sender: Callable[[str, Dict[str, Any]], Any], scanner: Any, template_mgr: Any, error_fn: Any):
        self.send_canvas_action = ws_action_sender
        self.scanner = scanner
        self.template_mgr = template_mgr
        self.get_error_fn = error_fn

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Returns OpenAPI/JSON schemas for all exposed agent tools."""
        return [
            {
                "name": "apply_graph_patch",
                "description": "Applies a batched modification to the ComfyUI canvas in a single turn. Can create nodes, update parameters, wire connections, and delete nodes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "creates": {
                            "type": "array",
                            "description": "List of nodes to create.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "description": "ComfyUI node type name (e.g. KSampler, VAEDecode)."},
                                    "ref": {"type": "string", "description": "Temporary ID (e.g. 'new_sampler') to reference in connections."},
                                    "pos": {"type": "array", "items": {"type": "number"}, "description": "[x, y] coordinates."},
                                    "widgets": {"type": "object", "description": "Key-value widget parameter values."},
                                },
                                "required": ["type", "ref"],
                            },
                        },
                        "updates": {
                            "type": "array",
                            "description": "List of widget parameter updates on existing nodes.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "node_id": {"type": "integer", "description": "Existing node ID on canvas."},
                                    "widgets": {"type": "object", "description": "Widget name to new value."},
                                },
                                "required": ["node_id", "widgets"],
                            },
                        },
                        "connects": {
                            "type": "array",
                            "description": "List of links to create.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "origin": {"type": "array", "description": "[node_id_or_ref, output_slot_name_or_index]"},
                                    "target": {"type": "array", "description": "[node_id_or_ref, input_slot_name]"},
                                },
                                "required": ["origin", "target"],
                            },
                        },
                        "deletes": {
                            "type": "array",
                            "description": "List of node IDs to delete from the canvas.",
                            "items": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "name": "get_current_graph",
                "description": "Returns the active compact workflow topology from the browser canvas (stripped of heavy UI metadata).",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "search_node_catalog",
                "description": "Searches installed core and third-party custom nodes by keyword to find valid node types.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search term (e.g., 'upscale', 'controlnet', 'flux')."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "resolve_model_pipeline",
                "description": "Finds compatible local checkpoints/UNETs, VAEs, and CLIPs for an architecture family.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string", "enum": ["flux", "sdxl", "sd15", "sd3"], "description": "Model architecture."},
                        "vram_preference": {"type": "string", "enum": ["low", "high", "auto"], "description": "VRAM optimization level."},
                    },
                    "required": ["family"],
                },
            },
            {
                "name": "queue_workflow",
                "description": "Triggers generation in ComfyUI by queueing the prompt.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_last_execution_error",
                "description": "Retrieves the latest intercepted ComfyUI execution traceback or error message for self-healing.",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "list_templates",
                "description": "Lists available modular subgraph templates (e.g. Hi-Res Fix, LoRA Stacker, Flux pipelines).",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "apply_template",
                "description": "Splices a pre-built subgraph template into the active canvas.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "template_name": {"type": "string", "description": "Name of template file (e.g. 'hires_fix')."},
                        "target_node_id": {"type": "integer", "description": "Optional node to position the template next to."},
                    },
                    "required": ["template_name"],
                },
            },
        ]

    async def execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Routes the tool invocation to the corresponding local handler or browser RPC."""
        try:
            if name == "apply_graph_patch":
                return await self.send_canvas_action("apply_graph_patch", args)

            elif name == "get_current_graph":
                return await self.send_canvas_action("get_current_graph", {})

            elif name == "search_node_catalog":
                query = args.get("query", "").lower()
                all_models = self.scanner.scan_all()
                import nodes
                matched_nodes = []
                for node_name, cls in nodes.NODE_CLASS_MAPPINGS.items():
                    if query in node_name.lower() or query in getattr(cls, "CATEGORY", "").lower():
                        matched_nodes.append({
                            "type": node_name,
                            "category": getattr(cls, "CATEGORY", ""),
                            "description": getattr(cls, "DESCRIPTION", ""),
                        })
                    if len(matched_nodes) >= 20:
                        break
                return {"matches": matched_nodes}

            elif name == "resolve_model_pipeline":
                family = args.get("family", "sdxl")
                vram_pref = args.get("vram_preference", "auto")
                vram_gb = 8.0 if vram_pref == "low" else (24.0 if vram_pref == "high" else 16.0)
                return self.scanner.resolve_companions(family, vram_gb=vram_gb)

            elif name == "queue_workflow":
                return await self.send_canvas_action("queue_workflow", {})

            elif name == "get_last_execution_error":
                err = self.get_error_fn()
                return {"error": err} if err else {"status": "no recent execution error"}

            elif name == "list_templates":
                return {"templates": self.template_mgr.list_templates()}

            elif name == "apply_template":
                tmpl = self.template_mgr.get_template(args.get("template_name", ""))
                if not tmpl:
                    return {"error": f"Template '{args.get('template_name')}' not found"}
                return await self.send_canvas_action("apply_template_data", {
                    "template": tmpl,
                    "target_node_id": args.get("target_node_id"),
                })

            else:
                return {"error": f"Unknown tool: {name}"}
        except Exception as e:
            logger.error(f"Error executing tool {name}: {e}", exc_info=True)
            return {"error": str(e)}

    dispatch = execute_tool

