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
