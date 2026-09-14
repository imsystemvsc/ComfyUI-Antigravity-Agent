/**
 * Dual-Mode Chat View (Sidebar + Floating Window).
 *
 * Implements shared-state DOM reparenting so user can toggle between
 * ComfyUI v2's native sidebar and a draggable floating modal with zero state loss.
 */

export class AntigravityChatView {
  constructor(app, executor) {
    this.app = app;
    this.executor = executor;
    this.isFloating = false;
    this.ws = null;
    this.messages = [];
    this.activeStreamingElem = null;
    this.engineStatus = null;

    this.initDOM();
    this.initWebSocket();
  }

  initDOM() {
    // 1. Root Container
    this.root = document.createElement("div");
    this.root.id = "antigravity-chat-root";
    this.root.className = "antigravity-chat-container docked";

    // 2. Header
    this.header = document.createElement("div");
    this.header.className = "antigravity-header";

    const titleBox = document.createElement("div");
    titleBox.className = "antigravity-title";
    titleBox.innerHTML = `
      <span class="antigravity-logo">✦</span>
      <span class="antigravity-title-text">Antigravity</span>
    `;

    const controlsBox = document.createElement("div");
    controlsBox.className = "antigravity-controls";

    // Revert Button
    this.btnRevert = document.createElement("button");
    this.btnRevert.className = "antigravity-btn antigravity-btn-subtle";
    this.btnRevert.title = "Revert last canvas change";
    this.btnRevert.innerHTML = "↶ Revert";
    this.btnRevert.onclick = () => this.handleRevert();

    // Engine / Model Selector Button
    this.btnEngine = document.createElement("button");
    this.btnEngine.className = "antigravity-btn antigravity-btn-subtle";
    this.btnEngine.title = "Antigravity Subscription & Model Settings";
    this.btnEngine.innerHTML = "✦ Engine";
    this.btnEngine.onclick = () => this.openEngineDialog();

    // Mode Switcher (Dock / Float)
    this.btnMode = document.createElement("button");
    this.btnMode.className = "antigravity-btn antigravity-btn-subtle";
    this.btnMode.title = "Toggle Floating / Docked Mode";
    this.btnMode.innerHTML = "⧉ Float";
    this.btnMode.onclick = () => this.toggleMode();

    controlsBox.appendChild(this.btnRevert);
    controlsBox.appendChild(this.btnEngine);
    controlsBox.appendChild(this.btnMode);

    this.header.appendChild(titleBox);
    this.header.appendChild(controlsBox);
    this.root.appendChild(this.header);

    // Setup drag logic for floating mode
    this.setupDraggable(this.header);

    // 3. Message List Area
    this.messageList = document.createElement("div");
    this.messageList.className = "antigravity-message-list";
    this.root.appendChild(this.messageList);

    // Initial greeting
    this.appendMessage(
      "assistant",
      "Hello! I am your **Antigravity Agent**, connected directly to your active Antigravity subscription in the background. I have full authority to construct, inspect, and wire your ComfyUI canvas with zero API keys. What would you like to build or modify?"
    );

    // 4. Input Area
    this.footer = document.createElement("div");
    this.footer.className = "antigravity-footer";

    const toolbar = document.createElement("div");
    toolbar.className = "antigravity-toolbar";
    toolbar.innerHTML = `
      <label class="antigravity-checkbox-label" title="Automatically trigger Queue Prompt when canvas edits finish">
        <input type="checkbox" id="antigravity-auto-queue" />
        Auto-Queue
      </label>
      <span class="antigravity-status" id="antigravity-status-pill">Connecting...</span>
    `;
    this.footer.appendChild(toolbar);

    const inputRow = document.createElement("div");
    inputRow.className = "antigravity-input-row";

    this.textarea = document.createElement("textarea");
    this.textarea.className = "antigravity-textarea";
    this.textarea.placeholder = "Describe workflow or parameter changes...";
    this.textarea.rows = 2;

    this.textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    this.btnSend = document.createElement("button");
    this.btnSend.className = "antigravity-send-btn";
    this.btnSend.innerHTML = "➤";
    this.btnSend.onclick = () => this.sendMessage();

    inputRow.appendChild(this.textarea);
    inputRow.appendChild(this.btnSend);
    this.footer.appendChild(inputRow);
    this.root.appendChild(this.footer);

    // Floating Wrapper attached to document.body
    this.floatingWrapper = document.createElement("div");
    this.floatingWrapper.id = "antigravity-floating-wrapper";
    this.floatingWrapper.className = "antigravity-floating-wrapper hidden";
    document.body.appendChild(this.floatingWrapper);
  }

  initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/antigravity/ws`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.updateStatusPill("Connecting to Sidecar...", "online");
      this.ws.send(JSON.stringify({ type: "get_engine_status" }));
    };

    this.ws.onclose = () => {
      this.updateStatusPill("Disconnected", "offline");
      setTimeout(() => this.initWebSocket(), 3000);
    };

    this.ws.onmessage = async (event) => {
      try {
        const data = JSON.parse(event.data);
        await this.handleServerMessage(data);
      } catch (e) {
        console.error("[Antigravity] WS parse error:", e);
      }
    };
  }

  updateStatusPill(text, stateClass) {
    const pill = this.root.querySelector("#antigravity-status-pill");
    if (pill) {
      pill.innerText = text;
      pill.className = `antigravity-status ${stateClass}`;
    }
  }

  updateEngineStatus(status) {
    this.engineStatus = status;
    if (status && status.running) {
      const modelName = status.model_info?.name || status.model || "Active";
      this.updateStatusPill(`✦ ${modelName}`, "online");
    } else {
      this.updateStatusPill("Antigravity Disconnected", "offline");
    }
  }

  async handleServerMessage(data) {
    const { type } = data;

    if (type === "engine_status") {
      this.updateEngineStatus(data.status);
    } else if (type === "token_delta") {
      this.streamToken(data.delta);
    } else if (type === "thought_delta") {
      this.streamThought(data.thought);
    } else if (type === "action_notice") {
      this.appendActionReceipt(data.tool, data.args);
    } else if (type === "canvas_action") {
      const { request_id, action, params } = data;
      let result = {};

      if (action === "apply_graph_patch") {
        result = this.executor.applyPatch(params);
        if (this.root.querySelector("#antigravity-auto-queue")?.checked) {
          this.app.queuePrompt(0);
        }
      } else if (action === "get_current_graph") {
        result = this.executor.captureSnapshot();
      } else if (action === "queue_workflow") {
        result = await this.app.queuePrompt(0);
      }

      this.ws.send(
        JSON.stringify({
          type: "canvas_action_result",
          request_id,
          result,
        })
      );
    }
  }

  sendMessage() {
    const text = this.textarea.value.trim();
    if (!text || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    this.appendMessage("user", text);
    this.textarea.value = "";

    // Send to server
    this.ws.send(
      JSON.stringify({
        type: "user_prompt",
        prompt: text,
      })
    );

    // Prepare assistant streaming container
    this.activeStreamingElem = this.appendMessage("assistant", "");
  }

  streamToken(token) {
    if (!this.activeStreamingElem) {
      this.activeStreamingElem = this.appendMessage("assistant", "");
    }
    const textElem = this.activeStreamingElem.querySelector(".antigravity-msg-text");
    if (textElem) {
      textElem.innerText += token;
    }
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  streamThought(thought) {
    if (!this.activeStreamingElem) {
      this.activeStreamingElem = this.appendMessage("assistant", "");
    }

    let thoughtBox = this.activeStreamingElem.querySelector(".antigravity-thought-box");
    if (!thoughtBox) {
      thoughtBox = document.createElement("div");
      thoughtBox.className = "antigravity-thought-box";
      thoughtBox.innerHTML = `
        <div class="antigravity-thought-header">✦ Antigravity Thinking</div>
        <div class="antigravity-thought-content"></div>
      `;
      this.activeStreamingElem.prepend(thoughtBox);
    }

    const contentElem = thoughtBox.querySelector(".antigravity-thought-content");
    contentElem.innerText = thought;
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  appendActionReceipt(toolName, args) {
    const receipt = document.createElement("div");
    receipt.className = "antigravity-action-receipt";
    receipt.innerHTML = `
      <span class="receipt-icon">⚡</span>
      <span class="receipt-text">Executing <b>${toolName}</b></span>
    `;
    this.messageList.appendChild(receipt);
    this.messageList.scrollTop = this.messageList.scrollHeight;
  }

  appendMessage(role, text) {
    const msg = document.createElement("div");
    msg.className = `antigravity-message ${role}`;

    const textElem = document.createElement("div");
    textElem.className = "antigravity-msg-text";
    textElem.innerText = text;

    msg.appendChild(textElem);
    this.messageList.appendChild(msg);
    this.messageList.scrollTop = this.messageList.scrollHeight;
    return msg;
  }

  handleRevert() {
    const res = this.executor.revertSnapshot();
    this.appendMessage("assistant", res.message);
  }

  openEngineDialog() {
    const status = this.engineStatus || {};
    const isRunning = status.running || false;
    const currentModel = status.model || "gemini-3.8-flash-high";
    const models = status.available_models || {
      "gemini-3.8-flash-high": "Gemini 3.8 Flash (High Thinking)",
      "gemini-3.7-flash-high": "Gemini 3.7 Flash (High Thinking)",
      "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    };

    const options = Object.entries(models)
      .map(([k, name]) => `${k === currentModel ? "▶" : "  "} [${k}]: ${name}`)
      .join("\n");

    const promptText = 
      `✦ Antigravity Background Engine\n` +
      `Status: ${isRunning ? `Connected (PID: ${status.pid}, Port: ${status.port})` : "Disconnected (Launch Antigravity)"}\n` +
      `Auth: Zero API Key Mode (Direct Subscription Sidecar)\n\n` +
      `Available Models:\n${options}\n\n` +
      `To switch model, enter model ID (e.g. gemini-3.8-flash-high, gemini-3.7-flash-high, claude-sonnet-4-6):`;

    const choice = prompt(promptText, currentModel);
    if (choice && choice.trim() && choice.trim() !== currentModel && models[choice.trim()]) {
      const selected = choice.trim();
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "set_model", model: selected }));
      }
      this.appendMessage("assistant", `✓ Switched active Antigravity model to **${models[selected]}**.`);
    }
  }

  toggleMode() {
    this.isFloating = !this.isFloating;

    if (this.isFloating) {
      this.floatingWrapper.appendChild(this.root);
      this.floatingWrapper.classList.remove("hidden");
      this.root.classList.remove("docked");
      this.root.classList.add("floating");
      this.btnMode.innerHTML = "⊟ Dock";
    } else {
      if (this.sidebarContainer) {
        this.sidebarContainer.appendChild(this.root);
      }
      this.floatingWrapper.classList.add("hidden");
      this.root.classList.remove("floating");
      this.root.classList.add("docked");
      this.btnMode.innerHTML = "⧉ Float";
    }
  }

  setupDraggable(header) {
    let isDragging = false;
    let startX = 0, startY = 0;

    header.addEventListener("mousedown", (e) => {
      if (!this.isFloating || e.target.tagName === "BUTTON" || e.target.tagName === "INPUT") return;
      isDragging = true;
      startX = e.clientX - this.floatingWrapper.offsetLeft;
      startY = e.clientY - this.floatingWrapper.offsetTop;
      document.body.style.userSelect = "none";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      this.floatingWrapper.style.left = `${Math.max(10, e.clientX - startX)}px`;
      this.floatingWrapper.style.top = `${Math.max(10, e.clientY - startY)}px`;
      this.floatingWrapper.style.right = "auto";
      this.floatingWrapper.style.bottom = "auto";
    });

    window.addEventListener("mouseup", () => {
      if (isDragging) {
        isDragging = false;
        document.body.style.userSelect = "";
      }
    });
  }

  attachToSidebar(container) {
    this.sidebarContainer = container;
    if (!this.isFloating) {
      container.appendChild(this.root);
    }
  }
}
