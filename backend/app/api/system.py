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
