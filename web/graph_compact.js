/**
 * Compact Graph Topology Serializer.
 *
 * Strips canvas coordinates, bounding boxes, link colors, and visual flags from app.graph.
 * Produces an ultra-compact JSON representation (~400 tokens) for minimal LLM token consumption.
 */

export function serializeCompactGraph(graph) {
  if (!graph) return {};

  const nodes = graph._nodes || [];
  const links = graph.links || {};
  const compact = {};

  for (const node of nodes) {
    const nodeData = {
      type: node.type,
      title: node.title || node.type,
      widgets: {},
      inputs: {},
    };

    // Serialize widget values by name
    if (node.widgets && Array.isArray(node.widgets)) {
      for (const w of node.widgets) {
        if (w.name) {
          nodeData.widgets[w.name] = w.value;
        }
      }
    }

    // Map input slot connections
    if (node.inputs && Array.isArray(node.inputs)) {
      for (let slotIdx = 0; slotIdx < node.inputs.length; slotIdx++) {
        const inputSlot = node.inputs[slotIdx];
        if (inputSlot.link !== null && inputSlot.link !== undefined) {
          const link = links[inputSlot.link];
          if (link) {
            // [origin_node_id, origin_slot_index]
            nodeData.inputs[inputSlot.name || `slot_${slotIdx}`] = [link.origin_id, link.origin_slot];
          }
        }
      }
    }

    compact[node.id] = nodeData;
  }

  return compact;
}
