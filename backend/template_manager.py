"""Template Manager.

Loads pre-bundled templates, handles conversational extraction ("Save selection as template"),
and analyzes boundary seams (exposed inputs and outputs) for subgraph splicing.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ComfyUI-Antigravity-Agent.TemplateManager")


class TemplateManager:
    """Manages pre-bundled and user-saved subgraph templates."""

    def __init__(self, templates_dir: Optional[Path] = None):
        if templates_dir is None:
            self.templates_dir = Path(__file__).resolve().parents[1] / "templates"
        else:
            self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)

    def list_templates(self) -> List[Dict[str, Any]]:
        """Returns list of all available templates with description and inputs/outputs."""
        results = []
        for file in self.templates_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    results.append({
                        "name": data.get("name", file.stem),
                        "description": data.get("description", ""),
                        "category": data.get("category", "General"),
                        "exposed_inputs": data.get("exposed_inputs", []),
                        "exposed_outputs": data.get("exposed_outputs", []),
                        "filename": file.name,
                    })
            except Exception as e:
                logger.warning(f"Failed to read template {file}: {e}")
        return results

    def get_template(self, name_or_file: str) -> Optional[Dict[str, Any]]:
        """Retrieves complete template JSON by name or filename."""
        target = self.templates_dir / (name_or_file if name_or_file.endswith(".json") else f"{name_or_file}.json")
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading template {target}: {e}")
                return None
        return None

    def save_extracted_template(
        self,
        name: str,
        description: str,
        selected_nodes: List[Dict[str, Any]],
        links: List[List[Any]],
    ) -> Dict[str, Any]:
        """Extracts a parameterized template from selected nodes and boundary links.

        boundary link: [link_id, origin_id, origin_slot, target_id, target_slot, type]
        """
        selected_ids = {node["id"] for node in selected_nodes}
        internal_links = []
        exposed_inputs = []
        exposed_outputs = []

        for link in links:
            if not link or len(link) < 6:
                continue
            link_id, origin_id, origin_slot, target_id, target_slot, slot_type = link[:6]

            is_origin_selected = origin_id in selected_ids
            is_target_selected = target_id in selected_ids

            if is_origin_selected and is_target_selected:
                internal_links.append(link)
            elif is_target_selected and not is_origin_selected:
                exposed_inputs.append({
                    "target_node_id": target_id,
                    "target_slot": target_slot,
                    "slot_type": slot_type,
                })
            elif is_origin_selected and not is_target_selected:
                exposed_outputs.append({
                    "origin_node_id": origin_id,
                    "origin_slot": origin_slot,
                    "slot_type": slot_type,
                })

        # Calculate relative coordinates (normalize to 0,0)
        min_x = min((node.get("pos", [0, 0])[0] for node in selected_nodes), default=0)
        min_y = min((node.get("pos", [0, 0])[1] for node in selected_nodes), default=0)

        normalized_nodes = []
        for node in selected_nodes:
            node_copy = dict(node)
            pos = node_copy.get("pos", [0, 0])
            node_copy["pos"] = [pos[0] - min_x, pos[1] - min_y]
            normalized_nodes.append(node_copy)

        template_data = {
            "name": name,
            "description": description,
            "exposed_inputs": exposed_inputs,
            "exposed_outputs": exposed_outputs,
            "nodes": normalized_nodes,
            "internal_links": internal_links,
        }

        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in name.lower())
        target_file = self.templates_dir / f"{clean_name}.json"
        with open(target_file, "w", encoding="utf-8") as f:
            json.dump(template_data, f, indent=2)

        return template_data
