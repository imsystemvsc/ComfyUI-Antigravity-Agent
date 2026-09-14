/**
 * ComfyUI-Antigravity-Agent Extension Entrypoint.
 *
 * Registers the extension with ComfyUI's app system, loads styles,
 * sets up the CanvasExecutor, and connects the Dual-Mode Antigravity Chat UI.
 */

import { app } from "../../scripts/app.js";
import { CanvasExecutor } from "./canvas_executor.js";
import { AntigravityChatView } from "./chat_view.js";

// Load CSS stylesheet
const link = document.createElement("link");
link.rel = "stylesheet";
link.type = "text/css";
link.href = new URL("./style.css", import.meta.url).href;
document.head.appendChild(link);

app.registerExtension({
  name: "ComfyUI.AntigravityAgent",

  async setup(app) {
    console.log("[ComfyUI-Antigravity-Agent] Initializing Extension...");

    const executor = new CanvasExecutor(app);
    const chatView = new AntigravityChatView(app, executor);

    // 1. Try registering with ComfyUI v2 Sidebar Extension Manager
    if (app.extensionManager && typeof app.extensionManager.registerSidebarTab === "function") {
      try {
        app.extensionManager.registerSidebarTab({
          id: "antigravity-agent-tab",
          icon: "pi pi-sparkles",
          title: "Antigravity",
          tooltip: "Antigravity AI Agent",
          type: "custom",
          render: (el) => {
            chatView.attachToSidebar(el);
          },
        });
        console.log("[ComfyUI-Antigravity-Agent] Successfully registered v2 Sidebar Tab.");
        return;
      } catch (e) {
        console.warn("[ComfyUI-Antigravity-Agent] Sidebar registration fallback:", e);
      }
    }

    // 2. Fallback for ComfyUI v1 / Classic Frontend: Add Menu Button to toggle Floating Window
    const menu = document.querySelector(".comfy-menu") || document.body;
    const btn = document.createElement("button");
    btn.className = "comfy-btn";
    btn.innerHTML = "✦ Antigravity";
    btn.style.marginTop = "6px";
    btn.onclick = () => {
      if (!chatView.isFloating) {
        chatView.toggleMode();
      } else {
        chatView.floatingWrapper.classList.toggle("hidden");
      }
    };

    if (menu) {
      menu.appendChild(btn);
    }

    // Default to floating mode if in v1 fallback
    chatView.toggleMode();
  },
});
