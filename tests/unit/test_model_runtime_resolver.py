from unittest.mock import MagicMock, patch

from utils.model_runtime_resolver import resolve_runtime_chat_model


def _mock_tags_response(models):
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b'{"models":[]}'
    resp.json.return_value = {
        "models": [{"name": name} for name in models]
    }
    return resp


def test_runtime_model_resolver_keeps_requested_when_available(monkeypatch):
    monkeypatch.setenv("TRION_RUNTIME_MODEL_RESOLVE", "true")
    monkeypatch.setenv("TRION_MODEL_TAGS_CACHE_TTL", "0")
    with patch("utils.model_runtime_resolver.requests.get", return_value=_mock_tags_response(["ministral-3:8b"])):
        out = resolve_runtime_chat_model(
            requested_model="ministral-3:8b",
            endpoint="http://ollama:11434",
            fallback_model="ministral-3:3b",
        )
    assert out["resolved_model"] == "ministral-3:8b"
    assert out["reason"] == "requested_available_exact"
    assert out["used_fallback"] is False


def test_runtime_model_resolver_uses_fallback_when_requested_missing(monkeypatch):
    monkeypatch.setenv("TRION_RUNTIME_MODEL_RESOLVE", "true")
    monkeypatch.setenv("TRION_MODEL_TAGS_CACHE_TTL", "0")
    with patch("utils.model_runtime_resolver.requests.get", return_value=_mock_tags_response(["ministral-3:8b", "qwen2.5:7b"])):
        out = resolve_runtime_chat_model(
            requested_model="jarvis",
            endpoint="http://ollama:11434",
            fallback_model="ministral-3:8b",
        )
    assert out["resolved_model"] == "ministral-3:8b"
    assert out["reason"] == "requested_unavailable_fallback_available"
    assert out["used_fallback"] is True


def test_runtime_model_resolver_uses_first_available_when_no_fallback_match(monkeypatch):
    monkeypatch.setenv("TRION_RUNTIME_MODEL_RESOLVE", "true")
    monkeypatch.setenv("TRION_MODEL_TAGS_CACHE_TTL", "0")
    with patch("utils.model_runtime_resolver.requests.get", return_value=_mock_tags_response(["m1:latest", "m2:latest"])):
        out = resolve_runtime_chat_model(
            requested_model="jarvis",
            endpoint="http://ollama:11434",
            fallback_model="not-installed:1b",
        )
    assert out["resolved_model"] == "m1:latest"
    assert out["reason"] == "requested_unavailable_first_available"
    assert out["used_fallback"] is True


def test_runtime_model_resolver_empty_request_model_uses_fallback(monkeypatch):
    monkeypatch.setenv("TRION_RUNTIME_MODEL_RESOLVE", "true")
    out = resolve_runtime_chat_model(
        requested_model="",
        endpoint="http://ollama:11434",
        fallback_model="ministral-3:8b",
    )
    assert out["resolved_model"] == "ministral-3:8b"
    assert out["reason"] == "empty_requested_model"


def test_runtime_model_resolver_tags_unavailable_falls_back(monkeypatch):
    monkeypatch.setenv("TRION_RUNTIME_MODEL_RESOLVE", "true")
    monkeypatch.setenv("TRION_MODEL_TAGS_CACHE_TTL", "0")
    with patch("utils.model_runtime_resolver.requests.get", side_effect=RuntimeError("network error")):
        out = resolve_runtime_chat_model(
            requested_model="jarvis",
            endpoint="http://ollama:11434",
            fallback_model="ministral-3:8b",
        )
    assert out["resolved_model"] == "ministral-3:8b"
    assert out["reason"] == "tags_unavailable_fallback_model"
    assert out["used_fallback"] is True

