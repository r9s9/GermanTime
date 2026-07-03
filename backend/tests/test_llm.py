"""LM Studio structured-generation repair path — the LLM client is faked so
this runs with no server and no network."""

import pytest
from pydantic import BaseModel

from app.services import llm


class Simple(BaseModel):
    value: int


class _FakeMessage:
    def __init__(self, content, reasoning_content=None):
        self.content = content
        self.reasoning_content = reasoning_content


class _FakeChoice:
    def __init__(self, content, reasoning_content=None):
        self.message = _FakeMessage(content, reasoning_content)


class _FakeResponse:
    def __init__(self, content, reasoning_content=None):
        self.choices = [_FakeChoice(content, reasoning_content)]


class _FakeCompletions:
    def __init__(self, contents):
        self._contents = list(contents)

    async def create(self, **kwargs):
        item = self._contents.pop(0)
        if isinstance(item, tuple):
            return _FakeResponse(item[0], item[1])
        return _FakeResponse(item)


class _FakeChat:
    def __init__(self, contents):
        self.completions = _FakeCompletions(contents)


class _FakeClient:
    def __init__(self, contents):
        self.chat = _FakeChat(contents)


def _stub_model_resolution(monkeypatch):
    async def fake_resolve(role):
        return "dummy-model"
    monkeypatch.setattr(llm, "resolve_model", fake_resolve)


@pytest.mark.asyncio
async def test_repair_path_recovers_from_invalid_json(monkeypatch):
    _stub_model_resolution(monkeypatch)
    fake = _FakeClient(["this is not json at all", '{"value": 42}'])
    monkeypatch.setattr(llm, "_client", lambda: fake)

    result = await llm.generate_structured("tutor", "sys", "usr", Simple, "simple", max_retries=1)
    assert result.value == 42


@pytest.mark.asyncio
async def test_repair_path_recovers_from_schema_violation(monkeypatch):
    _stub_model_resolution(monkeypatch)
    # valid JSON, but wrong type for `value` -> pydantic ValidationError, not a JSONDecodeError
    fake = _FakeClient(['{"value": "not-a-number"}', '{"value": 7}'])
    monkeypatch.setattr(llm, "_client", lambda: fake)

    result = await llm.generate_structured("tutor", "sys", "usr", Simple, "simple", max_retries=1)
    assert result.value == 7


@pytest.mark.asyncio
async def test_raises_after_exhausting_retries(monkeypatch):
    _stub_model_resolution(monkeypatch)
    fake = _FakeClient(["nope", "still nope"])
    monkeypatch.setattr(llm, "_client", lambda: fake)

    with pytest.raises(llm.LlmGenerationError):
        await llm.generate_structured("tutor", "sys", "usr", Simple, "simple", max_retries=1)


@pytest.mark.asyncio
async def test_falls_back_to_reasoning_content_when_content_empty(monkeypatch):
    """Regression test for "thinking" models (observed live with LM Studio +
    qwen3.5-35b-a3b) that route schema-constrained JSON entirely into
    reasoning_content and leave content empty."""
    _stub_model_resolution(monkeypatch)
    fake = _FakeClient([("", '{"value": 99}')])
    monkeypatch.setattr(llm, "_client", lambda: fake)

    result = await llm.generate_structured("tutor", "sys", "usr", Simple, "simple", max_retries=1)
    assert result.value == 99


@pytest.mark.asyncio
async def test_succeeds_first_try_without_repair(monkeypatch):
    _stub_model_resolution(monkeypatch)
    fake = _FakeClient(['{"value": 1}'])
    monkeypatch.setattr(llm, "_client", lambda: fake)

    result = await llm.generate_structured("tutor", "sys", "usr", Simple, "simple", max_retries=1)
    assert result.value == 1


class _FakeStreamChoice:
    def __init__(self, content=None, reasoning_content=None):
        self.delta = _FakeMessage(content, reasoning_content)


class _FakeStreamChunk:
    def __init__(self, content=None, reasoning_content=None):
        self.choices = [_FakeStreamChoice(content, reasoning_content)]


class _FakeStream:
    def __init__(self, deltas):
        self._deltas = deltas

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._deltas:
            raise StopAsyncIteration
        content, reasoning = self._deltas.pop(0)
        return _FakeStreamChunk(content, reasoning)


class _FakeStreamingCompletions:
    def __init__(self, deltas):
        self._deltas = deltas

    async def create(self, **kwargs):
        assert kwargs.get("stream") is True
        return _FakeStream(list(self._deltas))


class _FakeStreamingClient:
    def __init__(self, deltas):
        self.chat = type("_", (), {"completions": _FakeStreamingCompletions(deltas)})()


@pytest.mark.asyncio
async def test_stream_chat_yields_only_content_deltas(monkeypatch):
    _stub_model_resolution(monkeypatch)
    deltas = [(None, "Denke "), (None, "nach..."), ("Hallo", None), (" Welt", None)]
    monkeypatch.setattr(llm, "_client", lambda: _FakeStreamingClient(deltas))

    chunks = [c async for c in llm.stream_chat("fast", [{"role": "user", "content": "hi"}])]
    assert "".join(chunks) == "Hallo Welt"  # reasoning_content deltas are skipped


def _use_test_db_for_resolve_model(monkeypatch):
    """resolve_model() opens its own session via a module-level SessionLocal
    import, bound at collection time (before db_session's app.* purge) — so
    it needs its own patch to see the isolated test DB, unlike functions
    that take `db` as an explicit parameter."""
    from app.db import SessionLocal as fresh_session_local

    monkeypatch.setattr(llm, "SessionLocal", fresh_session_local)


@pytest.mark.asyncio
async def test_fast_role_avoids_thinking_models_when_auto_assigning(db_session, monkeypatch):
    _use_test_db_for_resolve_model(monkeypatch)

    async def fake_list_models():
        return ["qwen/qwen3.5-35b-a3b", "qwen2.5-14b-instruct", "text-embedding-nomic-embed-text-v1.5"]

    monkeypatch.setattr(llm, "list_models", fake_list_models)
    model_id = await llm.resolve_model("fast")
    assert model_id == "qwen2.5-14b-instruct"


@pytest.mark.asyncio
async def test_fast_role_prefers_recommended_model_over_generic(db_session, monkeypatch):
    _use_test_db_for_resolve_model(monkeypatch)

    async def fake_list_models():
        # A generic dense model is listed first, but the recommended one should win.
        return ["some-generic-8b-instruct", "qwen/qwen3-32b", "gemma-2-9b-it"]

    monkeypatch.setattr(llm, "list_models", fake_list_models)
    model_id = await llm.resolve_model("fast")
    assert model_id == "gemma-2-9b-it"  # preferred, and never the qwen3 thinking model


@pytest.mark.asyncio
async def test_fast_role_honors_preference_order(db_session, monkeypatch):
    _use_test_db_for_resolve_model(monkeypatch)

    async def fake_list_models():
        # Both are recommended; qwen2.5-14b outranks mistral-nemo in the list.
        return ["mistral-nemo-instruct-2407", "qwen2.5-14b-instruct"]

    monkeypatch.setattr(llm, "list_models", fake_list_models)
    model_id = await llm.resolve_model("fast")
    assert model_id == "qwen2.5-14b-instruct"


@pytest.mark.asyncio
async def test_tutor_role_prefers_larger_dense_model(db_session, monkeypatch):
    _use_test_db_for_resolve_model(monkeypatch)

    async def fake_list_models():
        return ["qwen/qwen3.5-35b-a3b", "qwen2.5-14b-instruct", "qwen2.5-32b-instruct"]

    monkeypatch.setattr(llm, "list_models", fake_list_models)
    model_id = await llm.resolve_model("tutor")
    assert model_id == "qwen2.5-32b-instruct"  # largest recommended dense model wins


@pytest.mark.asyncio
async def test_fast_role_falls_back_to_first_model_if_all_are_thinking_models(db_session, monkeypatch):
    _use_test_db_for_resolve_model(monkeypatch)

    async def fake_list_models():
        return ["qwen/qwen3.5-35b-a3b", "qwen/qwen3-32b"]

    monkeypatch.setattr(llm, "list_models", fake_list_models)
    model_id = await llm.resolve_model("fast")
    assert model_id == "qwen/qwen3.5-35b-a3b"
