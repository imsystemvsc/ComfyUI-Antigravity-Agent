# ComfyUI-Antigravity-Agent

An intelligent in-UI AI agent for ComfyUI powered by your local **Google Antigravity 2.0** runtime. Control, construct, wire, modify, and execute ComfyUI workflows via natural language chat directly inside ComfyUI with **full canvas authority** and **zero API keys**.

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)
![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)
![ComfyUI](https://img.shields.io/badge/ComfyUI-Frontend%20v1%20%26%20v2-orange.svg)

---

## Highlights

* **Zero API Keys & No Cloud Billing:** Directly harnesses your local Google Antigravity 2.0 runtime binary and existing subscription entitlements (`~/.gemini/antigravity`). The Antigravity desktop app does not even need to be open.
* **Dual-Mode UI:** Seamlessly switch between a docked sidebar panel (native to ComfyUI v2) and a floating, draggable, resizable window with zero-loss DOM reparenting (chat history and state are preserved).
* **Full Canvas Authority:** The agent can build workflows from scratch, inspect active graphs, delete or rewire nodes, modify parameters/widgets, and trigger generations.
* **Model & Companion Intelligence:** Detects architecture (Flux, SDXL, SD 1.5, SD 3) and container formats (GGUF, NVFP4, FP8, standard `.safetensors`). Uses mathematical tensor fingerprinting (16-channel vs. 4-channel VAEs, CLIP-L, CLIP-G, T5-XXL) to pair compatible encoders and VAEs automatically.
* **Token Optimization Engine:** Employs ultra-compact graph serialization (reducing graph tokens by ~98%) and single-turn macro patches (reducing multi-turn roundtrips by ~90%).
* **Safety & Instant Rollback:** Automatically captures pre-action canvas snapshots with a one-click `[ ↶ Revert Changes ]` button in the chat header.
* **Autonomous Error Recovery:** Intercepts ComfyUI `execution_error` events (OOMs, dimension mismatches, missing inputs) to diagnose issues and auto-patch the graph.
* **Modular Subgraph Templates:** Includes pre-bundled starter workflows (Flux Dev GGUF, SDXL Base, Hi-Res Fix) and supports one-click conversational extraction (*"Save my selected nodes as a template"*).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ComfyUI Browser Window                   │
│                                                             │
│   ┌───────────────────────────┐      ┌──────────────────┐   │
│   │ Dual-Mode Chat Panel      │◄────►│ LiteGraph Canvas │   │
│   │ (Sidebar ⧉ Floating Window)│      │ (app.graph)      │   │
│   └─────────────▲─────────────┘      └─────────▲────────┘   │
└─────────────────┼──────────────────────────────┼────────────┘
                  │ WebSocket (/antigravity/ws)   │
                  ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│             ComfyUI Backend (Python Custom Node)            │
│                                                             │
│   ┌─────────────────────┐       ┌───────────────────────┐   │
│   │ aiohttp WS Server   │◄─────►│ Action/Patch Executor │   │
│   └──────────▲──────────┘       └───────────────────────┘   │
│              │                                              │
│   ┌──────────▼──────────┐       ┌───────────────────────┐   │
│   │ Antigravity Agent   │◄─────►│ Model & VAE Scanner   │   │
│   │ (google-antigravity)│       │ (Tensor Shape Matcher)│   │
│   └──────────▲──────────┘       └───────────────────────┘   │
└──────────────┼──────────────────────────────────────────────┘
               │ Local Subprocess & Auth
               ▼
┌─────────────────────────────────────────────────────────────┐
│             Local Machine (Host Environment)                │
│                                                             │
│   ~/.gemini/antigravity  (Active subscription & tokens)     │
└─────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

1. **ComfyUI:** A working local installation of ComfyUI.
2. **Google Antigravity:** Antigravity 2.0 installed and authenticated on your machine at least once (`agy` or the Antigravity desktop app).
3. **Python:** Python 3.10 or higher.

---

## Installation

### 1. Clone into `custom_nodes`
Navigate to your ComfyUI directory and clone the repository into `custom_nodes`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/imsystemvsc/ComfyUI-Antigravity-Agent.git
```

### 2. Install Dependencies
Activate your ComfyUI Python environment and install the required packages:

```bash
# In your ComfyUI virtualenv or portable python:
pip install -r ComfyUI-Antigravity-Agent/requirements.txt
```

### 3. Restart ComfyUI
Launch ComfyUI. You will see an Antigravity icon appear in the ComfyUI sidebar and a toggle for the floating window.

---

## Usage & Example Prompts

### Constructing Workflows
* *"Build a complete Flux Dev GGUF pipeline using Euler sampler and 25 steps."*
* *"Create an SDXL text-to-image workflow with a Refiner pass."*
* *"Add an Ultimate SD Upscale node after my KSampler and wire the VAE and model."*

### Modifying Parameters
* *"Change CFG to 1.0 and set steps to 20 for Flux."*
* *"Swap the sampler to DPM++ 2M Karras."*
* *"Update the positive prompt to: 'a futuristic solarpunk city at sunset, 8k, cinematic shot'."*

### Managing Models & Companions
* *"Switch to my fastest Flux model."* (Agent checks VRAM and selects appropriate GGUF/FP8 variant).
* *"Find all installed LoRAs that match 'film style' and insert them."*

### Templates & Extraction
* *"Save my selected nodes as a template named 'fast-2x-upscale'."*
* *"Insert the Hi-Res Fix template and connect it to my current sampler."*

### Error Diagnostics
* *"Why did the generation fail?"* (Agent analyzes the intercepted traceback and repairs the missing connection or adjusts image dimensions).

---

## Configuration (`config.json`)

Customize settings in `config.json` (or create `config.local.json` for local overrides):

```json
{
  "auto_queue": false,
  "vram_threshold_gb": 16,
  "vision_thumbnail_max_dim": 512,
  "ui_mode_default": "sidebar",
  "history_window_turns": 8,
  "default_pairings": {
    "flux": {
      "clip1": "clip_l.safetensors",
      "clip2_low_vram": "t5xxl_fp8_e4m3fn.safetensors",
      "clip2_high_vram": "t5xxl_fp16.safetensors",
      "vae": "ae.safetensors"
    }
  }
}
```

* **`auto_queue`**: If `true`, the agent automatically queues the prompt after modifying the canvas. If `false`, it prompts you to confirm.
* **`vram_threshold_gb`**: VRAM threshold for choosing between FP8 and FP16 text encoders.
* **`vision_thumbnail_max_dim`**: Max pixel resolution for images sent to the vision agent (conserves vision tokens).

---

## Troubleshooting & FAQ

#### Does the Antigravity desktop app need to stay open?
**No.** The `google-antigravity` Python SDK runs headlessly and reads your saved credentials from `~/.gemini/antigravity`.

#### How do I revert changes made by the agent?
Click the `[ ↶ Revert Changes ]` button in the chat header. The canvas immediately reverts to the snapshot captured right before the agent's action.

#### GGUF / NF4 models are failing to load?
Ensure the required custom node loaders (such as `ComfyUI-GGUF`) are installed in your `custom_nodes/` directory. If missing, the agent will alert you in the chat.

---

## License

This project is licensed under the [MIT License](LICENSE).
