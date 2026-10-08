from types import SimpleNamespace

import pytest

from app.extract import ExtractedClaims
from app.llm import GeminiProvider, LLMError, get_provider


class FakeModels:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=next(self.responses), parsed=None)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def test_gemini_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        get_provider()


def test_gemini_model_and_json_schema_request(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    client = FakeClient(['{"claims": []}'])
    provider = GeminiProvider(client=client)

    result = provider.structured("test", "Return an empty claims object", ExtractedClaims)

    assert result.claims == []
    call = client.models.calls[0]
    assert call["model"] == "gemini-3.5-flash"
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_schema["properties"]["claims"]["type"] == "array"


def test_gemini_structured_response_repairs_once(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    client = FakeClient(["not json", '{"claims": []}'])
    provider = GeminiProvider(client=client)

    result = provider.structured("repair-test", "Return claims", ExtractedClaims)

    assert result.claims == []
    assert len(client.models.calls) == 2


def test_gemini_is_only_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    provider = get_provider()
    assert isinstance(provider, GeminiProvider)
    assert provider.model == "gemini-3.5-flash"


def test_non_gemini_provider_names_are_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "other")
    with pytest.raises(LLMError, match="only gemini"):
        get_provider()
