"""Shared GPU busy-lock. The background content factory acquires this around
LLM calls; P6's voice pipeline will acquire it too so a live conversation
always wins GPU priority over speculative background generation.
"""

import asyncio

gpu_lock = asyncio.Lock()
