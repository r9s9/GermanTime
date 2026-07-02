"""System endpoints: health, GPU status, LM Studio model discovery."""

import platform
import sys
from functools import lru_cache

from fastapi import APIRouter

from ..services.llm import server_status

router = APIRouter(prefix="/api", tags=["system"])


@lru_cache(maxsize=1)
def _torch_info() -> dict:
    try:
        import torch

        cuda = torch.cuda.is_available()
        return {
            "version": torch.__version__,
            "cuda": cuda,
            "device": torch.cuda.get_device_name(0) if cuda else None,
            "sm_120": "sm_120" in torch.cuda.get_arch_list() if cuda else False,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


@router.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "torch": _torch_info(),
        "lmstudio": await server_status(),
    }


@router.get("/models")
async def models() -> dict:
    return await server_status()


# Chatterbox measured ~5-6GB resident (see memory: project-chatterbox-latency)
# on top of whatever LM Studio's model + whisper/piper already hold; below
# this much free VRAM, loading it risks OOM-evicting the LLM mid-conversation.
CHATTERBOX_MIN_FREE_GB = 6.0


@router.get("/vram")
def vram() -> dict:
    """Live GPU memory query (not model-metadata guessing) — mem_get_info()
    reflects actual system-wide VRAM state, including whatever LM Studio's
    own process already has resident.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return {"available": False}
        free_bytes, total_bytes = torch.cuda.mem_get_info()
        free_gb = free_bytes / (1024 ** 3)
        return {
            "available": True,
            "free_gb": round(free_gb, 1),
            "total_gb": round(total_bytes / (1024 ** 3), 1),
            "used_gb": round((total_bytes - free_bytes) / (1024 ** 3), 1),
            "chatterbox_safe": free_gb >= CHATTERBOX_MIN_FREE_GB,
        }
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}
