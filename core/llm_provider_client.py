"""
Provider-aware LLM client helpers for TRION layers.

Supported providers:
- ollama    (local, current default)
- ollama_cloud (Ollama Cloud API)
- openai    (Chat Completions API)
- anthropic (Messages API)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Iterable, List, Tuple

import httpx

from config import (
    get_control_provider,
    get_output_model,
    get_output_provider,
    get_secret_resolve_miss_ttl_s,
    get_secret_resolve_not_found_ttl_s,
    get_thinking_provider,
)
from core.secret_resolve_runtime import (
    clear_provider_miss,
    mark_provider_miss,
    mark_secret_not_found,
    mark_secret_success,
    order_candidates,
    provider_miss_active,
    secret_not_found_active,
)


_PROVIDER_VALUES = {"ollama", "ollama_cloud", "openai", "anthropic"}
_API_KEY_CACHE: Dict[str, Tuple[float, str]] = {}
_API_KEY_TTL_S = 20.0
_RATE_LIMIT_LOCK = threading.Lock()
_RATE_LIMIT_SNAPSHOT: Dict[str, Dict[str, Any]] = {}


def normalize_provider(raw: str, default: str = "ollama") -> str:
    provider = str(raw or "").strip().lower()
    return provider if provider in _PROVIDER_VALUES else default


def resolve_role_provider(role: str, default: str = "ollama") -> str:
    role_norm = str(role or "").strip().lower()
    if role_norm == "thinking":
        return normalize_provider(get_thinking_provider(), default=default)
    if role_norm == "control":
        return normalize_provider(get_control_provider(), default=default)
    if role_norm == "output":
        return normalize_provider(get_output_provider(), default=default)
    return normalize_provider(default, default="ollama")


def _openai_base() -> str:
    return str(os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")).rstrip("/")


def _anthropic_base() -> str:
    return str(os.getenv("ANTHROPIC_API_BASE", "https://api.anthropic.com/v1")).rstrip("/")


def _ollama_cloud_base() -> str:
    return str(
        os.getenv(
            "OLLAMA_CLOUD_BASE",
            os.getenv("OLLAMA_API_BASE", "https://ollama.com"),
        )
    ).rstrip("/")


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        txt = str(value).strip()
        if not txt:
            return None
        # Accept plain numbers and structured header values like "1000;w=60" or "1000, 5000;w=3600".
        m = re.search(r"-?\d+(?:\.\d+)?", txt)
        if not m:
            return None
        return int(float(m.group(0)))
    except Exception:
        return None


def _pick_header(headers: Dict[str, str], keys: Iterable[str]) -> str:
    for key in keys:
        val = str(headers.get(str(key).lower(), "")).strip()
        if val:
            return val
    return ""


def _capture_rate_limit_headers(provider: str, headers_obj: Any, status_code: int = 0) -> None:
    provider_norm = normalize_provider(provider)
    if provider_norm not in {"openai", "anthropic", "ollama_cloud"}:
        return

    lower_headers: Dict[str, str] = {}
    try:
        if hasattr(headers_obj, "items"):
            for key, value in headers_obj.items():
                lower_headers[str(key).lower()] = str(value)
    except Exception:
        lower_headers = {}

    raw = {
        key: value
        for key, value in lower_headers.items()
        if ("ratelimit" in key or key in {"retry-after", "x-request-id", "request-id", "anthropic-request-id"})
    }

    request_limit = _to_int(_pick_header(lower_headers, (
        "x-ratelimit-limit-requests",
        "x-ratelimit-requests-limit",
        "ratelimit-limit-requests",
        "anthropic-ratelimit-requests-limit",
        "x-ratelimit-limit",
    )))
    request_remaining = _to_int(_pick_header(lower_headers, (
        "x-ratelimit-remaining-requests",
        "x-ratelimit-requests-remaining",
        "ratelimit-remaining-requests",
        "anthropic-ratelimit-requests-remaining",
        "x-ratelimit-remaining",
    )))
    request_reset = _pick_header(lower_headers, (
        "x-ratelimit-reset-requests",
        "x-ratelimit-requests-reset",
        "ratelimit-reset-requests",
        "anthropic-ratelimit-requests-reset",
        "x-ratelimit-reset",
        "retry-after",
    ))

    token_limit = _to_int(_pick_header(lower_headers, (
        "x-ratelimit-limit-tokens",
        "x-ratelimit-tokens-limit",
        "ratelimit-limit-tokens",
        "anthropic-ratelimit-tokens-limit",
    )))
    token_remaining = _to_int(_pick_header(lower_headers, (
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-tokens-remaining",
        "ratelimit-remaining-tokens",
        "anthropic-ratelimit-tokens-remaining",
    )))
    token_reset = _pick_header(lower_headers, (
        "x-ratelimit-reset-tokens",
        "x-ratelimit-tokens-reset",
        "ratelimit-reset-tokens",
        "anthropic-ratelimit-tokens-reset",
    ))

    payload: Dict[str, Any] = {
        "provider": provider_norm,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status_code": int(status_code or 0),
        "request_id": _pick_header(lower_headers, ("x-request-id", "request-id", "anthropic-request-id")),
        "request_limit": request_limit,
        "request_remaining": request_remaining,
        "request_reset": request_reset,
        "token_limit": token_limit,
        "token_remaining": token_remaining,
        "token_reset": token_reset,
        "raw": raw,
    }

    with _RATE_LIMIT_LOCK:
        _RATE_LIMIT_SNAPSHOT[provider_norm] = payload


def get_rate_limit_snapshot() -> Dict[str, Dict[str, Any]]:
    with _RATE_LIMIT_LOCK:
        return {
            key: dict(value)
            for key, value in _RATE_LIMIT_SNAPSHOT.items()
        }


def _flatten_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: List[str] = []
        for item in content:
            if isinstance(item, str):
                out.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                txt = str(item.get("text") or "")
                if txt:
                    out.append(txt)
        return "".join(out)
    return str(content or "")


def _normalize_openai_messages(messages: Iterable[Dict[str, Any]]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        if role not in {"system", "user", "assistant"}:
            role = "user"
        content = _flatten_content(msg.get("content"))
        if not content:
            continue
        out.append({"role": role, "content": content})
    if not out:
        out.append({"role": "user", "content": ""})
    return out


def _normalize_anthropic_messages(messages: Iterable[Dict[str, Any]]) -> Tuple[str, List[Dict[str, str]]]:
    system_parts: List[str] = []
    out: List[Dict[str, str]] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user").strip().lower()
        content = _flatten_content(msg.get("content"))
        if not content:
            continue
        if role == "system":
            system_parts.append(content)
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        out.append({"role": role, "content": content})
    if not out:
        out.append({"role": "user", "content": ""})
    return ("\n\n".join(system_parts).strip(), out)


def _looks_cross_provider_model_name(model_name: str) -> bool:
    low = str(model_name or "").strip().lower()
    if not low:
        return False
    return (
        low.startswith("gpt-")
        or low.startswith("o1")
        or low.startswith("o3")
        or low.startswith("o4")
        or low.startswith("claude")
    )


def _ollama_cloud_model_candidates(requested_model: str) -> List[str]:
    out: List[str] = []
    preferred = str(requested_model or "").strip()
    output_model = str(get_output_model() or "").strip()
    cross_provider_name = _looks_cross_provider_model_name(preferred)

    if cross_provider_name:
        if output_model:
            out.append(output_model)
        if preferred and preferred not in out:
            out.append(preferred)
    else:
        if preferred:
            out.append(preferred)
        if output_model and output_model not in out:
            out.append(output_model)
    return out or [preferred]


async def _resolve_cloud_api_key(provider: str) -> str:
    provider_norm = normalize_provider(provider)
    if provider_norm == "ollama":
        return ""

    now = time.monotonic()
    provider_miss_ttl_s = max(0, int(get_secret_resolve_miss_ttl_s() or 0))
    candidate_not_found_ttl_s = max(0, int(get_secret_resolve_not_found_ttl_s() or 0))

    cached = _API_KEY_CACHE.get(provider_norm)
    if cached and (now - float(cached[0])) < _API_KEY_TTL_S and cached[1]:
        return cached[1]
    if provider_miss_active(provider_norm, now, provider_miss_ttl_s):
        return ""

    if provider_norm == "openai":
        env_candidates = ("OPENAI_API_KEY", "OPENAI_KEY")
        secret_candidates = ("OPENAI_API_KEY", "OPENAI_KEY")
    elif provider_norm == "ollama_cloud":
        env_candidates = ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY", "OLLAMA")
        secret_candidates = ("OLLAMA_API_KEY", "OLLAMA_CLOUD_API_KEY", "OLLAMA_KEY", "OLLAMA")
    else:
        env_candidates = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_KEY")
        secret_candidates = ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "ANTHROPIC_KEY")

    for env_name in env_candidates:
        value = str(os.getenv(env_name, "")).strip()
        if value:
            _API_KEY_CACHE[provider_norm] = (now, value)
            mark_secret_success(provider_norm, env_name)
            return value

    token = str(os.getenv("INTERNAL_SECRET_RESOLVE_TOKEN", "")).strip()
    base = str(
        os.getenv("SECRETS_API_URL", "http://jarvis-admin-api:8200/api/secrets/resolve")
    ).strip().rstrip("/")
    if not token or not base:
        mark_provider_miss(provider_norm, now)
        return ""

    headers = {"Authorization": f"Bearer {token}"}
    ordered_candidates = order_candidates(provider_norm, secret_candidates)
    attempted_remote = False
    saw_not_found = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            for name in ordered_candidates:
                if secret_not_found_active(
                    provider_norm,
                    name,
                    now,
                    candidate_not_found_ttl_s,
                ):
                    continue
                try:
                    attempted_remote = True
                    resp = await client.get(f"{base}/{name}", headers=headers)
                    if resp.status_code == 404:
                        saw_not_found = True
                        mark_secret_not_found(provider_norm, name, now)
                        continue
                    if resp.status_code != 200:
                        continue
                    data = resp.json() if resp.content else {}
                    value = str((data or {}).get("value") or "").strip()
                    if value:
                        _API_KEY_CACHE[provider_norm] = (now, value)
                        mark_secret_success(provider_norm, name)
                        clear_provider_miss(provider_norm)
                        return value
                    saw_not_found = True
                    mark_secret_not_found(provider_norm, name, now)
                except Exception:
                    continue
    except Exception:
        return ""

    if saw_not_found or not attempted_remote:
        mark_provider_miss(provider_norm, now)
    return ""


async def complete_prompt(
    *,
    provider: str,
    model: str,
    prompt: str,
    timeout_s: float = 90.0,
    ollama_endpoint: str = "",
    json_mode: bool = False,
) -> str:
    provider_norm = normalize_provider(provider)
    model_name = str(model or "").strip()

    if provider_norm in {"ollama", "ollama_cloud"}:
        headers: Dict[str, str] = {}
        endpoint = str(ollama_endpoint).rstrip("/")
        if provider_norm == "ollama_cloud":
            api_key = await _resolve_cloud_api_key(provider_norm)
            if not api_key:
                raise RuntimeError(f"missing_api_key:{provider_norm}")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            endpoint = _ollama_cloud_base()
        if not endpoint:
            raise RuntimeError(f"missing_endpoint:{provider_norm}")

        # Ollama Cloud currently serves prompt-style requests reliably via /api/chat.
        # Keep local ollama behavior on /api/generate for compatibility.
        if provider_norm == "ollama_cloud":
            last_exc: Exception | None = None
            for candidate_model in _ollama_cloud_model_candidates(model_name):
                payload: Dict[str, Any] = {
                    "model": candidate_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                    "keep_alive": "2m",
                }
                parts: List[str] = []
                try:
                    async with httpx.AsyncClient(timeout=timeout_s) as client:
                        async with client.stream(
                            "POST",
                            f"{endpoint}/api/chat",
                            json=payload,
                            headers=headers or None,
                        ) as response:
                            _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    data = json.loads(line)
                                except Exception:
                                    continue
                                msg = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
                                chunk = _flatten_content(msg.get("content"))
                                if chunk:
                                    parts.append(chunk)
                                if data.get("done"):
                                    break
                    return "".join(parts).strip()
                except httpx.HTTPStatusError as e:
                    last_exc = e
                    code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                    if code == 404:
                        continue
                    raise
            if last_exc:
                raise last_exc
            raise RuntimeError("ollama_cloud_prompt_failed_no_candidate")

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "keep_alive": "2m",
        }
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(f"{endpoint}/api/generate", json=payload, headers=headers or None)
            _capture_rate_limit_headers(provider_norm, r.headers, r.status_code)
            r.raise_for_status()
            data = r.json()
        return str(data.get("response", "") or data.get("thinking", "")).strip()

    api_key = await _resolve_cloud_api_key(provider_norm)
    if not api_key:
        raise RuntimeError(f"missing_api_key:{provider_norm}")

    if provider_norm == "openai":
        body: Dict[str, Any] = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(f"{_openai_base()}/chat/completions", json=body, headers=headers)
            _capture_rate_limit_headers(provider_norm, r.headers, r.status_code)
            r.raise_for_status()
            data = r.json()
        choices = data.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        return _flatten_content(msg.get("content")).strip()

    body = {
        "model": model_name,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(f"{_anthropic_base()}/messages", json=body, headers=headers)
        _capture_rate_limit_headers(provider_norm, r.headers, r.status_code)
        r.raise_for_status()
        data = r.json()
    content_items = data.get("content") or []
    out: List[str] = []
    for item in content_items:
        if isinstance(item, dict) and item.get("type") == "text":
            text = str(item.get("text") or "")
            if text:
                out.append(text)
    return "".join(out).strip()


async def stream_prompt(
    *,
    provider: str,
    model: str,
    prompt: str,
    timeout_s: float = 90.0,
    ollama_endpoint: str = "",
) -> AsyncGenerator[str, None]:
    provider_norm = normalize_provider(provider)
    model_name = str(model or "").strip()

    if provider_norm in {"ollama", "ollama_cloud"}:
        headers: Dict[str, str] = {}
        endpoint = str(ollama_endpoint).rstrip("/")
        if provider_norm == "ollama_cloud":
            api_key = await _resolve_cloud_api_key(provider_norm)
            if not api_key:
                raise RuntimeError(f"missing_api_key:{provider_norm}")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            endpoint = _ollama_cloud_base()
        if not endpoint:
            raise RuntimeError(f"missing_endpoint:{provider_norm}")

        if provider_norm == "ollama_cloud":
            payload = {
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                "keep_alive": "2m",
            }
            last_exc: Exception | None = None
            for candidate_model in _ollama_cloud_model_candidates(model_name):
                payload["model"] = candidate_model
                try:
                    async with httpx.AsyncClient(timeout=timeout_s) as client:
                        async with client.stream(
                            "POST",
                            f"{endpoint}/api/chat",
                            json=payload,
                            headers=headers or None,
                        ) as response:
                            _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                try:
                                    data = json.loads(line)
                                except Exception:
                                    continue
                                msg = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
                                chunk = _flatten_content(msg.get("content"))
                                if chunk:
                                    yield chunk
                                if data.get("done"):
                                    break
                    return
                except httpx.HTTPStatusError as e:
                    last_exc = e
                    code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                    if code == 404:
                        continue
                    raise
            if last_exc:
                raise last_exc
            raise RuntimeError("ollama_cloud_stream_prompt_failed_no_candidate")
            return

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": True,
            "keep_alive": "2m",
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream(
                "POST",
                f"{endpoint}/api/generate",
                json=payload,
                headers=headers or None,
            ) as response:
                _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except Exception:
                        continue
                    chunk = str(data.get("response", "") or "")
                    if chunk:
                        yield chunk
                    if data.get("done"):
                        break
        return

    api_key = await _resolve_cloud_api_key(provider_norm)
    if not api_key:
        raise RuntimeError(f"missing_api_key:{provider_norm}")

    if provider_norm == "openai":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream(
                "POST",
                f"{_openai_base()}/chat/completions",
                json=body,
                headers=headers,
            ) as response:
                _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    choices = data.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    chunk = _flatten_content(delta.get("content"))
                    if chunk:
                        yield chunk
        return

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model_name,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        async with client.stream(
            "POST",
            f"{_anthropic_base()}/messages",
            json=body,
            headers=headers,
        ) as response:
            _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except Exception:
                    continue
                if str(data.get("type") or "") != "content_block_delta":
                    continue
                delta = data.get("delta", {}) if isinstance(data.get("delta"), dict) else {}
                chunk = str(delta.get("text") or "")
                if chunk:
                    yield chunk


async def complete_chat(
    *,
    provider: str,
    model: str,
    messages: Iterable[Dict[str, Any]],
    timeout_s: float = 90.0,
    ollama_endpoint: str = "",
    tools: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    provider_norm = normalize_provider(provider)
    model_name = str(model or "").strip()

    if provider_norm in {"ollama", "ollama_cloud"}:
        headers: Dict[str, str] = {}
        endpoint = str(ollama_endpoint).rstrip("/")
        if provider_norm == "ollama_cloud":
            api_key = await _resolve_cloud_api_key(provider_norm)
            if not api_key:
                raise RuntimeError(f"missing_api_key:{provider_norm}")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            endpoint = _ollama_cloud_base()
        if not endpoint:
            raise RuntimeError(f"missing_endpoint:{provider_norm}")

        candidate_models = (
            _ollama_cloud_model_candidates(model_name)
            if provider_norm == "ollama_cloud"
            else [model_name]
        )
        last_exc: Exception | None = None
        data: Dict[str, Any] = {}
        for candidate_model in candidate_models:
            payload: Dict[str, Any] = {
                "model": candidate_model,
                "messages": list(messages or []),
                "stream": False,
                "keep_alive": "5m",
            }
            if tools:
                payload["tools"] = tools
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    response = await client.post(
                        f"{endpoint}/api/chat",
                        json=payload,
                        headers=headers or None,
                    )
                    _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPStatusError as e:
                last_exc = e
                code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                if provider_norm == "ollama_cloud" and code == 404:
                    continue
                raise
        else:
            if last_exc:
                raise last_exc
            raise RuntimeError(f"{provider_norm}_complete_chat_failed_no_candidate")
        msg = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
        return {
            "content": _flatten_content(msg.get("content")).strip(),
            "tool_calls": msg.get("tool_calls", []) if isinstance(msg.get("tool_calls"), list) else [],
        }

    api_key = await _resolve_cloud_api_key(provider_norm)
    if not api_key:
        raise RuntimeError(f"missing_api_key:{provider_norm}")

    if provider_norm == "openai":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model_name,
            "messages": _normalize_openai_messages(messages),
            "temperature": 0,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                f"{_openai_base()}/chat/completions",
                json=body,
                headers=headers,
            )
            _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
            response.raise_for_status()
            data = response.json()
        choices = data.get("choices") or []
        msg = choices[0].get("message", {}) if choices else {}
        tool_calls = msg.get("tool_calls", []) if isinstance(msg.get("tool_calls"), list) else []
        return {"content": _flatten_content(msg.get("content")).strip(), "tool_calls": tool_calls}

    system, norm_messages = _normalize_anthropic_messages(messages)
    body: Dict[str, Any] = {
        "model": model_name,
        "max_tokens": 4096,
        "messages": norm_messages,
    }
    if system:
        body["system"] = system
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(f"{_anthropic_base()}/messages", json=body, headers=headers)
        _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
        response.raise_for_status()
        data = response.json()
    content_items = data.get("content") or []
    out: List[str] = []
    for item in content_items:
        if isinstance(item, dict) and item.get("type") == "text":
            txt = str(item.get("text") or "")
            if txt:
                out.append(txt)
    return {"content": "".join(out).strip(), "tool_calls": []}


async def stream_chat(
    *,
    provider: str,
    model: str,
    messages: Iterable[Dict[str, Any]],
    timeout_s: float = 90.0,
    ollama_endpoint: str = "",
) -> AsyncGenerator[str, None]:
    provider_norm = normalize_provider(provider)
    model_name = str(model or "").strip()

    if provider_norm in {"ollama", "ollama_cloud"}:
        headers: Dict[str, str] = {}
        endpoint = str(ollama_endpoint).rstrip("/")
        if provider_norm == "ollama_cloud":
            api_key = await _resolve_cloud_api_key(provider_norm)
            if not api_key:
                raise RuntimeError(f"missing_api_key:{provider_norm}")
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            endpoint = _ollama_cloud_base()
        if not endpoint:
            raise RuntimeError(f"missing_endpoint:{provider_norm}")

        candidate_models = (
            _ollama_cloud_model_candidates(model_name)
            if provider_norm == "ollama_cloud"
            else [model_name]
        )
        last_exc: Exception | None = None
        for candidate_model in candidate_models:
            payload = {
                "model": candidate_model,
                "messages": list(messages or []),
                "stream": True,
                "keep_alive": "5m",
            }
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    async with client.stream(
                        "POST",
                        f"{endpoint}/api/chat",
                        json=payload,
                        headers=headers or None,
                    ) as response:
                        _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except Exception:
                                continue
                            msg = data.get("message", {}) if isinstance(data.get("message"), dict) else {}
                            chunk = _flatten_content(msg.get("content"))
                            if chunk:
                                yield chunk
                            if data.get("done"):
                                break
                return
            except httpx.HTTPStatusError as e:
                last_exc = e
                code = int(getattr(getattr(e, "response", None), "status_code", 0) or 0)
                if provider_norm == "ollama_cloud" and code == 404:
                    continue
                raise
        if last_exc:
            raise last_exc
        raise RuntimeError(f"{provider_norm}_stream_chat_failed_no_candidate")
        return

    api_key = await _resolve_cloud_api_key(provider_norm)
    if not api_key:
        raise RuntimeError(f"missing_api_key:{provider_norm}")

    if provider_norm == "openai":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        body = {
            "model": model_name,
            "messages": _normalize_openai_messages(messages),
            "temperature": 0,
            "stream": True,
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            async with client.stream(
                "POST",
                f"{_openai_base()}/chat/completions",
                json=body,
                headers=headers,
            ) as response:
                _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        data = json.loads(payload)
                    except Exception:
                        continue
                    choices = data.get("choices") or []
                    delta = choices[0].get("delta", {}) if choices else {}
                    chunk = _flatten_content(delta.get("content"))
                    if chunk:
                        yield chunk
        return

    system, norm_messages = _normalize_anthropic_messages(messages)
    body: Dict[str, Any] = {
        "model": model_name,
        "max_tokens": 4096,
        "messages": norm_messages,
        "stream": True,
    }
    if system:
        body["system"] = system
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        async with client.stream(
            "POST",
            f"{_anthropic_base()}/messages",
            json=body,
            headers=headers,
        ) as response:
            _capture_rate_limit_headers(provider_norm, response.headers, response.status_code)
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    data = json.loads(payload)
                except Exception:
                    continue
                if str(data.get("type") or "") != "content_block_delta":
                    continue
                delta = data.get("delta", {}) if isinstance(data.get("delta"), dict) else {}
                chunk = str(delta.get("text") or "")
                if chunk:
                    yield chunk
