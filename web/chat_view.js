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

    // Mode Switcher (Dock / Float)
    this.btnMode = document.createElement("button");
    this.btnMode.className = "antigravity-btn antigravity-btn-subtle";
    this.btnMode.title = "Toggle Floating / Docked Mode";
    this.btnMode.innerHTML = "⧉ Float";
    this.btnMode.onclick = () => this.toggleMode();

    controlsBox.appendChild(this.btnRevert);
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
      "Hello! I am your local **Antigravity Agent**. I have full authority to construct, rewire, and tune your ComfyUI canvas without API keys. What would you like to build or adjust?"
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
      <span class="antigravity-status" id="antigravity-status-pill">Connected</span>
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

    // Floating wrapper container appended to body
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
      const pill = this.root.querySelector("#antigravity-status-pill");
      if (pill) {
        pill.innerText = "Connected";
        pill.className = "antigravity-status online";
      }
    };

    this.ws.onclose = () => {
      const pill = this.root.querySelector("#antigravity-status-pill");
      if (pill) {
        pill.innerText = "Disconnected";
        pill.className = "antigravity-status offline";
      }
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

  async handleServerMessage(data) {
    const { type } = data;

    if (type === "token_delta") {
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
          this.executor.queueWorkflow();
        }
      } else if (action === "get_current_graph") {
        result = this.executor.getCompactGraph();
      } else if (action === "apply_template_data") {
        result = this.executor.applyTemplate(params.template, params.target_node_id);
      } else if (action === "queue_workflow") {
        result = this.executor.queueWorkflow();
      }

      this.ws.send(
        JSON.stringify({
          type: "canvas_action_result",
          request_id: request_id,
          result: result,
        })
      );
    }
  }

  sendMessage() {
    const text = this.textarea.value.trim();
    if (!text || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

    this.appendMessage("user", text);
    this.textarea.value = "";

    this.activeStreamingElem = this.appendMessage("assistant", "");

    this.ws.send(
      JSON.stringify({
        type: "user_prompt",
        prompt: text,
      })
    );
  }

  streamToken(token) {
    if (!this.activeStreamingElem) {
      this.activeStreamingElem = this.appendMessage("assistant", "");
    }
    const contentBox = this.activeStreamingElem.querySelector(".antigravity-msg-text");
    if (contentBox) {
      contentBox.innerText += token;
      this.messageList.scrollTop = this.messageList.scrollHeight;
    }
  }

  streamThought(thought) {
    // Displays subtle collapsible reasoning indicator
    if (!this.activeStreamingElem) {
      this.activeStreamingElem = this.appendMessage("assistant", "");
    }
    let thoughtBox = this.activeStreamingElem.querySelector(".antigravity-thought-box");
    if (!thoughtBox) {
      thoughtBox = document.createElement("div");
      thoughtBox.className = "antigravity-thought-box";
      this.activeStreamingElem.insertBefore(thoughtBox, this.activeStreamingElem.firstChild);
    }
    thoughtBox.innerText = `Thinking: ${thought}`;
  }

  appendActionReceipt(toolName, args) {
    const receipt = document.createElement("div");
    receipt.className = "antigravity-receipt";
    receipt.innerHTML = `⚙ Executed <strong>${toolName}</strong>`;
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

  toggleMode() {
    this.isFloating = !this.isFloating;

    if (this.isFloating) {
      // Reparent to floating wrapper in body
      this.floatingWrapper.appendChild(this.root);
      this.floatingWrapper.classList.remove("hidden");
      this.root.classList.remove("docked");
      this.root.classList.add("floating");
      this.btnMode.innerHTML = "⊟ Dock";
    } else {
      // Reparent back to sidebar container
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
