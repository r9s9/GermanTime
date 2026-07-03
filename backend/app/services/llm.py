"""LM Studio client: model-role resolution and schema-constrained generation.

Every structured call goes through `generate_structured`, which asks LM Studio
for `response_format: json_schema` (derived straight from a pydantic model),
validates the result, and repairs once by feeding the error back to the model
before giving up.
"""

import json
import logging
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .. import config
from ..db import SessionLocal
from ..models import ModelRole

logger = logging.getLogger(__name__)

_client_instance: AsyncOpenAI | None = None


class LlmGenerationError(Exception):
    pass


def _client() -> AsyncOpenAI:
    global _client_instance
    if _client_instance is None:
        _client_instance = AsyncOpenAI(base_url=config.LMSTUDIO_BASE_URL, api_key="lm-studio")
    return _client_instance


async def server_status() -> dict:
    """Distinguishes "server unreachable" from "reachable, zero models"."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{config.LMSTUDIO_BASE_URL}/models")
            r.raise_for_status()
            return {"reachable": True, "models": [m["id"] for m in r.json().get("data", [])]}
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "models": [], "error": str(e)}


async def list_models() -> list[str]:
    return (await server_status())["models"]


# Model-name substrings for known "thinking" models where unconstrained chat
# has a multi-hundred-ms-to-seconds think-before-answering delay (measured:
# qwen3.5-35b-a3b took ~650ms-2.7s to first content token depending on
# whether thinking fired) — unsuitable for the <1.5s conversational budget.
# Only biases the "fast" role's auto-pick; the user can always override via
# Settings. See memory: project-lmstudio-thinking-models.
_THINKING_MODEL_HINTS = ("qwen3", "qwq", "deepseek-r1", "r1-")

# Ordered preference for the "fast" (real-time conversation) role. Dense,
# non-reasoning 7-14B models that hit the <1.5s first-token budget with strong
# German. First available match wins; falls back to any non-thinking model.
# (MoE models are excluded in spirit — measured 6.6-29s first token — but the
# thinking-hint filter plus this positive list keeps auto-pick on known-good
# dense models without needing an explicit MoE denylist.)
_PREFERRED_FAST_HINTS = (
    "qwen2.5-14b",
    "mistral-nemo",
    "gemma-2-9b",
    "qwen2.5-7b",
    "ministral",
    "llama-3.1-8b",
)

# Ordered preference for the "tutor"/grader role (not latency-bound): larger
# dense models first for better exercise/exam generation and grading quality.
_PREFERRED_TUTOR_HINTS = (
    "qwen2.5-32b",
    "gemma-2-27b",
    "qwen2.5-14b",
    "gemma-2-9b",
)


def _pick_preferred(models: list[str], hints: tuple[str, ...]) -> str | None:
    """First model whose id contains a hint, honoring hint order."""
    lowered = [(m, m.lower()) for m in models]
    for hint in hints:
        for original, low in lowered:
            if hint in low:
                return original
    return None


async def resolve_model(role: str) -> str:
    """Return the model_id assigned to `role`, auto-assigning a suitable
    chat model on first use so the app works before the user visits
    Settings. The "fast" role (real-time conversation) prefers a model
    that isn't a known "thinking" model, since those blow the latency
    budget even with schema/thinking disabled.
    """
    with SessionLocal() as db:
        row = db.get(ModelRole, role)
        if row:
            return row.model_id

    models = await list_models()
    chat_models = [m for m in models if "embed" not in m.lower()]
    if not chat_models:
        raise LlmGenerationError(
            "Kein Modell in LM Studio verfügbar. Bitte LM Studio starten und ein Modell laden."
        )
    if role == "fast":
        non_thinking = [m for m in chat_models if not any(h in m.lower() for h in _THINKING_MODEL_HINTS)]
        pool = non_thinking or chat_models
        chosen = _pick_preferred(pool, _PREFERRED_FAST_HINTS) or pool[0]
    elif role == "tutor":
        chosen = _pick_preferred(chat_models, _PREFERRED_TUTOR_HINTS) or chat_models[0]
    else:
        chosen = chat_models[0]
    with SessionLocal() as db:
        if db.get(ModelRole, role) is None:  # avoid clobbering a concurrent assignment
            db.add(ModelRole(role=role, model_id=chosen))
            db.commit()
    if role == "tutor":
        config.ensure_dirs()
        (config.DATA_DIR / "tutor_model.txt").write_text(chosen, encoding="utf-8")
    return chosen


def _effective_content(message) -> str:
    """Some "thinking" models (Qwen3 family, at least under this LM Studio
    build) route schema-constrained JSON output entirely into
    `reasoning_content` and leave `content` empty, regardless of an
    enable_thinking=False chat_template_kwarg. Fall back to it so structured
    generation still works for those models.
    """
    content = message.content
    if content and content.strip():
        return content
    return getattr(message, "reasoning_content", None) or ""


async def generate_structured(
    role: str,
    system: str,
    user: str,
    model_cls: type[BaseModel],
    schema_name: str,
    temperature: float = 0.7,
    max_retries: int = 1,
) -> BaseModel:
    model_id = await resolve_model(role)
    schema = model_cls.model_json_schema()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        resp = await _client().chat.completions.create(
            model=model_id,
            messages=messages,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
            temperature=temperature,
        )
        content = _effective_content(resp.choices[0].message)
        try:
            data = json.loads(content)
            return model_cls.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = e
            logger.warning("generate_structured(%s) attempt %d invalid: %s", schema_name, attempt, e)
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    f"Das war kein gültiges JSON für dieses Schema. Fehler: {e}. "
                    "Antworte NUR mit korrektem JSON, das exakt dem Schema entspricht."
                ),
            })

    raise LlmGenerationError(f"{schema_name}: failed after {max_retries + 1} attempts: {last_err}")


async def chat_text(role: str, system: str, user: str, temperature: float = 0.7) -> str:
    model_id = await resolve_model(role)
    resp = await _client().chat.completions.create(
        model=model_id,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return _effective_content(resp.choices[0].message)


async def stream_chat(role: str, messages: list[dict], temperature: float = 0.8) -> AsyncIterator[str]:
    """Yields content text deltas as they arrive. Silently skips
    reasoning_content deltas (a thinking model assigned here will still
    eventually stream real content once it finishes thinking — just slowly;
    that's a model-choice problem for the caller/user to fix via Settings,
    not something to paper over here).
    """
    model_id = await resolve_model(role)
    stream = await _client().chat.completions.create(
        model=model_id, messages=messages, temperature=temperature, stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            yield delta.content
