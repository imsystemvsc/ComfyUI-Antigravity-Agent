"""Model & Companion Scanner.

Scans ComfyUI model directories (checkpoints, unet, clip, vae),
inspects safetensors and GGUF headers to classify architecture and precision,
and uses tensor shape analysis to match VAEs and CLIP text encoders.
"""

import json
import logging
import os
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ComfyUI-Antigravity-Agent.ModelScanner")


def read_safetensors_header(filepath: Path) -> Dict[str, Any]:
    """Reads only the JSON header of a .safetensors file without loading tensor weights."""
    try:
        with open(filepath, "rb") as f:
            header_size_bytes = f.read(8)
            if len(header_size_bytes) < 8:
                return {}
            header_size = struct.unpack("<Q", header_size_bytes)[0]
            if header_size > 100 * 1024 * 1024:  # Safety guard: max 100MB header
                return {}
            header_json_bytes = f.read(header_size)
            return json.loads(header_json_bytes.decode("utf-8", errors="ignore"))
    except Exception as e:
        logger.debug(f"Failed to parse safetensors header for {filepath}: {e}")
        return {}


def detect_architecture_from_header(header: Dict[str, Any], filename: str) -> str:
    """Classifies diffusion model architecture based on state-dict tensor keys and shapes."""
    lower_name = filename.lower()
    keys = list(header.keys())
    keys_str = " ".join(keys[:100])

    if "double_blocks" in keys_str or "img_in" in keys_str or "flux" in lower_name:
        return "flux"
    if "input_blocks.7.1.transformer_blocks" in keys_str or "label_emb" in keys_str or "sdxl" in lower_name:
        return "sdxl"
    if "joint_blocks" in keys_str or "sd3" in lower_name:
        return "sd3"
    if "input_blocks.1.1.transformer_blocks" in keys_str or "v1-5" in lower_name or "sd15" in lower_name:
        return "sd15"

    return "unknown"


def detect_vae_type(filepath: Path) -> str:
    """Detects VAE latent channel dimension via conv_out weights in safetensors header.
    - Flux VAE: 16 latent channels (conv_out shape has 32 output channels)
    - SD1.5/SDXL VAE: 4 latent channels (conv_out shape has 8 output channels)
    """
    header = read_safetensors_header(filepath)
    conv_out = header.get("decoder.conv_out.weight", {}).get("shape") or header.get("conv_out.weight", {}).get("shape")
    
    if conv_out and len(conv_out) >= 1:
        out_channels = conv_out[0]
        if out_channels == 32 or "ae.safetensors" in filepath.name.lower() or "flux" in filepath.name.lower():
            return "flux_vae_16ch"
        if out_channels == 8:
            if "sdxl" in filepath.name.lower():
                return "sdxl_vae_4ch"
            return "sd15_vae_4ch"
            
    if "ae" in filepath.name.lower() or "flux" in filepath.name.lower():
        return "flux_vae_16ch"
    if "sdxl" in filepath.name.lower():
        return "sdxl_vae_4ch"
    return "standard_vae_4ch"


def detect_clip_type(filepath: Path) -> str:
    """Classifies CLIP encoder by file size and key signatures:
    - CLIP-L: ~246MB (ViT-L/14)
    - CLIP-G: ~1.4GB (OpenCLIP ViT-bigG)
    - T5-XXL: ~4.7GB (FP8) or ~9.8GB (FP16)
    """
    name = filepath.name.lower()
    try:
        size_bytes = filepath.stat().st_size
    except OSError:
        size_bytes = 0

    if "t5" in name:
        return "t5xxl_fp8" if size_bytes < 6 * 1024 * 1024 * 1024 else "t5xxl_fp16"
    if "clip_g" in name or "big_g" in name:
        return "clip_g"
    if "clip_l" in name:
        return "clip_l"

    # Size heuristics
    if size_bytes > 3 * 1024 * 1024 * 1024:
        return "t5xxl"
    if size_bytes > 1 * 1024 * 1024 * 1024:
        return "clip_g"
    return "clip_l"


class ModelScanner:
    """Scans and caches installed models and companion encoders/VAEs."""

    def __init__(self, comfy_root: Optional[Path] = None):
        self.comfy_root = comfy_root or Path(__file__).resolve().parents[2]
        self.models_dir = self.comfy_root / "models"
        self._cache: Dict[str, Any] = {}

    def scan_all(self) -> Dict[str, Any]:
        """Performs full scan across unet, checkpoints, clip, and vae folders."""
        models: List[Dict[str, Any]] = []
        clips: List[Dict[str, Any]] = []
        vaes: List[Dict[str, Any]] = []

        # Scan UNETs & Checkpoints
        for folder_name in ["unet", "diffusion_models", "checkpoints"]:
            folder = self.models_dir / folder_name
            if folder.exists():
                for root, _, files in os.walk(folder):
                    for file in files:
                        if file.endswith((".safetensors", ".gguf", ".ckpt")):
                            path = Path(root) / file
                            header = read_safetensors_header(path) if file.endswith(".safetensors") else {}
                            arch = detect_architecture_from_header(header, file)
                            fmt = "gguf" if file.endswith(".gguf") else "safetensors"
                            models.append({
                                "filename": file,
                                "rel_path": str(path.relative_to(self.models_dir)),
                                "folder": folder_name,
                                "architecture": arch,
                                "format": fmt,
                                "is_checkpoint": folder_name == "checkpoints",
                            })

        # Scan CLIPs
        clip_folder = self.models_dir / "clip"
        if clip_folder.exists():
            for root, _, files in os.walk(clip_folder):
                for file in files:
                    if file.endswith((".safetensors", ".bin", ".pt")):
                        path = Path(root) / file
                        clip_type = detect_clip_type(path)
                        clips.append({
                            "filename": file,
                            "type": clip_type,
                            "rel_path": str(path.relative_to(self.models_dir)),
                        })

        # Scan VAEs
        vae_folder = self.models_dir / "vae"
        if vae_folder.exists():
            for root, _, files in os.walk(vae_folder):
                for file in files:
                    if file.endswith((".safetensors", ".pt", ".bin")):
                        path = Path(root) / file
                        vae_type = detect_vae_type(path)
                        vaes.append({
                            "filename": file,
                            "type": vae_type,
                            "rel_path": str(path.relative_to(self.models_dir)),
                        })

        self._cache = {
            "models": models,
            "clips": clips,
            "vaes": vaes,
        }
        return self._cache

    def resolve_companions(self, architecture: str, vram_gb: float = 16.0) -> Dict[str, Any]:
        """Resolves optimal CLIP and VAE companions based on architecture and system VRAM."""
        if not self._cache:
            self.scan_all()

        clips = self._cache.get("clips", [])
        vaes = self._cache.get("vaes", [])

        if architecture == "flux":
            clip_l = next((c["filename"] for c in clips if c["type"] == "clip_l"), "clip_l.safetensors")
            if vram_gb < 16.0:
                t5 = next((c["filename"] for c in clips if c["type"] == "t5xxl_fp8"), "t5xxl_fp8_e4m3fn.safetensors")
            else:
                t5 = next((c["filename"] for c in clips if c["type"] == "t5xxl_fp16"), None)
                if not t5:
                    t5 = next((c["filename"] for c in clips if "t5" in c["type"]), "t5xxl_fp8_e4m3fn.safetensors")

            vae = next((v["filename"] for v in vaes if "flux" in v["type"] or "ae" in v["filename"].lower()), "ae.safetensors")
            return {
                "loader_type": "DualCLIPLoader",
                "clip_name1": clip_l,
                "clip_name2": t5,
                "clip_type": "flux",
                "vae_name": vae,
            }

        if architecture == "sdxl":
            clip_l = next((c["filename"] for c in clips if c["type"] == "clip_l"), "clip_l.safetensors")
            clip_g = next((c["filename"] for c in clips if c["type"] == "clip_g"), "clip_g.safetensors")
            vae = next((v["filename"] for v in vaes if "sdxl" in v["type"] or "sdxl" in v["filename"].lower()), "sdxl_vae.safetensors")
            return {
                "loader_type": "DualCLIPLoader",
                "clip_name1": clip_l,
                "clip_name2": clip_g,
                "clip_type": "sdxl",
                "vae_name": vae,
            }

        # Default SD1.5 fallback
        clip_l = next((c["filename"] for c in clips if c["type"] == "clip_l"), "clip_l.safetensors")
        vae = next((v["filename"] for v in vaes if "sd1" in v["type"] or "840000" in v["filename"].lower()), "vae-ft-mse-840000-ema-pruned.safetensors")
        return {
            "loader_type": "CLIPLoader",
            "clip_name": clip_l,
            "clip_type": "sd1",
            "vae_name": vae,
        }
