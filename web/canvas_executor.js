/**
 * Canvas Action Executor.
 *
 * Executes JSON-RPC actions directly on ComfyUI's app.graph:
 * - Macro graph patching (creates, connects, updates, deletes)
 * - Snapshot & rollback buffer for instant one-click revert
 * - Subgraph template instantiation & splicing
 * - Queueing prompt execution
 */

import { serializeCompactGraph } from "./graph_compact.js";

class CanvasExecutor {
  constructor(app) {
    this.app = app;
    this.snapshotBuffer = [];
    this.maxSnapshots = 10;
  }

  get graph() {
    return this.app.graph;
  }

  takeSnapshot() {
    if (!this.graph) return;
    try {
      const serialized = this.graph.serialize();
      this.snapshotBuffer.push(JSON.stringify(serialized));
      if (this.snapshotBuffer.length > this.maxSnapshots) {
        this.snapshotBuffer.shift();
      }
    } catch (e) {
      console.warn("[Antigravity] Failed to create canvas snapshot:", e);
    }
  }

  revertSnapshot() {
    if (this.snapshotBuffer.length === 0) {
      return { success: false, message: "No snapshots available in rollback buffer." };
    }
    const previous = this.snapshotBuffer.pop();
    try {
      const data = JSON.parse(previous);
      this.app.loadGraphData(data);
      this.graph.setDirtyCanvas(true, true);
      return { success: true, message: "Canvas reverted to prior state." };
    } catch (e) {
      return { success: false, message: `Revert failed: ${e.message}` };
    }
  }

  getCompactGraph() {
    return serializeCompactGraph(this.graph);
  }

  applyPatch(patch) {
    if (!this.graph) {
      return { success: false, error: "No active graph found on canvas." };
    }

    // Step 1: Capture pre-action snapshot
    this.takeSnapshot();

    const createdRefs = {}; // ref -> node
    const results = { created: [], updated: [], connected: [], deleted: [] };

    try {
      // Step 2: Handle Creations
      if (Array.isArray(patch.creates)) {
        for (const item of patch.creates) {
          const nodeType = item.type;
          const ref = item.ref;
          const pos = item.pos || [100, 100];
          const widgets = item.widgets || {};

          const node = window.LiteGraph.createNode(nodeType);
          if (!node) {
            console.warn(`[Antigravity] Node type '${nodeType}' not recognized.`);
            continue;
          }

          node.pos = [pos[0], pos[1]];
          this.graph.add(node);

          // Apply initial widget values
          if (node.widgets && Array.isArray(node.widgets)) {
            for (const [wName, wVal] of Object.entries(widgets)) {
              const widget = node.widgets.find((w) => w.name === wName);
              if (widget) {
                widget.value = wVal;
                if (widget.callback) widget.callback(wVal);
              }
            }
          }

          createdRefs[ref] = node;
          results.created.push({ ref, id: node.id, type: nodeType });
        }
      }

      // Step 3: Handle Parameter Updates
      if (Array.isArray(patch.updates)) {
        for (const update of patch.updates) {
          const node = this.graph.getNodeById(update.node_id);
          if (node && node.widgets && update.widgets) {
            for (const [wName, wVal] of Object.entries(update.widgets)) {
              const widget = node.widgets.find((w) => w.name === wName);
              if (widget) {
                widget.value = wVal;
                if (widget.callback) widget.callback(wVal);
                results.updated.push({ node_id: node.id, widget: wName, value: wVal });
              }
            }
          }
        }
      }

      // Helper to resolve node reference
      const resolveNode = (idOrRef) => {
        if (typeof idOrRef === "number" || (!isNaN(idOrRef) && typeof idOrRef === "string" && !isNaN(Number(idOrRef)))) {
          return this.graph.getNodeById(Number(idOrRef));
        }
        return createdRefs[idOrRef];
      };

      // Step 4: Handle Connections
      if (Array.isArray(patch.connects)) {
        for (const conn of patch.connects) {
          const [originRef, originSlot] = conn.origin;
          const [targetRef, targetSlot] = conn.target;

          const originNode = resolveNode(originRef);
          const targetNode = resolveNode(targetRef);

          if (!originNode || !targetNode) {
            console.warn(`[Antigravity] Could not resolve connection endpoints: ${originRef} -> ${targetRef}`);
            continue;
          }

          // Find origin slot index
          let outIndex = typeof originSlot === "number" ? originSlot : 0;
          if (typeof originSlot === "string" && originNode.outputs) {
            const foundIdx = originNode.outputs.findIndex(
              (o) => o.name.toLowerCase() === originSlot.toLowerCase() || o.type.toLowerCase() === originSlot.toLowerCase()
            );
            if (foundIdx !== -1) outIndex = foundIdx;
          }

          // Find target slot index
          let inIndex = typeof targetSlot === "number" ? targetSlot : 0;
          if (typeof targetSlot === "string" && targetNode.inputs) {
            const foundIdx = targetNode.inputs.findIndex(
              (i) => i.name.toLowerCase() === targetSlot.toLowerCase() || i.type.toLowerCase() === targetSlot.toLowerCase()
            );
            if (foundIdx !== -1) inIndex = foundIdx;
          }

          originNode.connect(outIndex, targetNode, inIndex);
          results.connected.push({
            from: [originNode.id, outIndex],
            to: [targetNode.id, inIndex],
          });
        }
      }

      // Step 5: Handle Deletions
      if (Array.isArray(patch.deletes)) {
        for (const delId of patch.deletes) {
          const node = this.graph.getNodeById(delId);
          if (node) {
            this.graph.remove(node);
            results.deleted.push(delId);
          }
        }
      }

      this.graph.setDirtyCanvas(true, true);
      return { success: true, results };
    } catch (e) {
      console.error("[Antigravity] Patch application error:", e);
      return { success: false, error: e.message };
    }
  }

  applyTemplate(templateData, targetNodeId) {
    if (!templateData || !Array.isArray(templateData.nodes)) {
      return { success: false, error: "Invalid template format." };
    }

    this.takeSnapshot();

    let baseX = 100;
    let baseY = 100;

    if (targetNodeId) {
      const targetNode = this.graph.getNodeById(targetNodeId);
      if (targetNode) {
        baseX = targetNode.pos[0] + (targetNode.size ? targetNode.size[0] : 200) + 60;
        baseY = targetNode.pos[1];
      }
    }

    const idMap = {}; // old_id -> new_node

    // Create template nodes
    for (const nodeDef of templateData.nodes) {
      const node = window.LiteGraph.createNode(nodeDef.type);
      if (!node) continue;

      const pos = nodeDef.pos || [0, 0];
      node.pos = [baseX + pos[0], baseY + pos[1]];
      if (nodeDef.size) node.size = [...nodeDef.size];

      this.graph.add(node);
      idMap[nodeDef.id] = node;

      if (node.widgets && Array.isArray(nodeDef.widgets_values)) {
        for (let i = 0; i < nodeDef.widgets_values.length && i < node.widgets.length; i++) {
          node.widgets[i].value = nodeDef.widgets_values[i];
        }
      }
    }

    // Recreate internal links
    if (Array.isArray(templateData.internal_links)) {
      for (const link of templateData.internal_links) {
        const [, originId, originSlot, targetId, targetSlot] = link;
        const oNode = idMap[originId];
        const tNode = idMap[targetId];
        if (oNode && tNode) {
          oNode.connect(originSlot, tNode, targetSlot);
        }
      }
    }

    this.graph.setDirtyCanvas(true, true);
    return { success: true, added_nodes_count: Object.keys(idMap).length };
  }

  queueWorkflow() {
    try {
      if (this.app.queuePrompt) {
        this.app.queuePrompt(0);
        return { success: true, message: "Prompt queued via ComfyUI app." };
      }
      return { success: false, error: "app.queuePrompt function not found on active window." };
    } catch (e) {
      return { success: false, error: e.message };
    }
  }
}

export { CanvasExecutor };
