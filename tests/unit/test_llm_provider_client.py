from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import core.llm_provider_client as client
from core.secret_resolve_runtime import reset_secret_resolve_runtime_state


class TestLLMProviderClient(unittest.TestCase):
    def setUp(self):
        client._API_KEY_CACHE.clear()
        reset_secret_resolve_runtime_state()

    def test_normalize_provider_supported(self):
        self.assertEqual(client.normalize_provider("openai"), "openai")
        self.assertEqual(client.normalize_provider("anthropic"), "anthropic")
        self.assertEqual(client.normalize_provider("ollama"), "ollama")
        self.assertEqual(client.normalize_provider("ollama_cloud"), "ollama_cloud")

    def test_normalize_provider_unknown_falls_back(self):
        self.assertEqual(client.normalize_provider("x"), "ollama")
        self.assertEqual(client.normalize_provider("", default="openai"), "openai")

    def test_resolve_role_provider_uses_role_getters(self):
        with patch.object(client, "get_thinking_provider", return_value="openai"), \
             patch.object(client, "get_control_provider", return_value="anthropic"), \
             patch.object(client, "get_output_provider", return_value="ollama"):
            self.assertEqual(client.resolve_role_provider("thinking"), "openai")
            self.assertEqual(client.resolve_role_provider("control"), "anthropic")
            self.assertEqual(client.resolve_role_provider("output"), "ollama")

    def test_normalize_openai_messages_maps_unknown_roles(self):
        msgs = [
            {"role": "system", "content": "policy"},
            {"role": "developer", "content": "treat as user"},
            {"role": "assistant", "content": "ok"},
        ]
        out = client._normalize_openai_messages(msgs)
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(out[1]["role"], "user")
        self.assertEqual(out[2]["role"], "assistant")

    def test_normalize_anthropic_messages_collects_system(self):
        system, out = client._normalize_anthropic_messages(
            [
                {"role": "system", "content": "A"},
                {"role": "system", "content": "B"},
                {"role": "user", "content": "Hi"},
            ]
        )
        self.assertEqual(system, "A\n\nB")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["role"], "user")

    def test_resolve_cloud_api_key_supports_ollama_cloud_env_candidates(self):
        with patch.dict(
            os.environ,
            {
                "OLLAMA_API_KEY": "",
                "OLLAMA_CLOUD_API_KEY": "",
                "OLLAMA_KEY": "",
                "OLLAMA": "ollama-cloud-secret",
                "INTERNAL_SECRET_RESOLVE_TOKEN": "",
            },
            clear=False,
        ):
            value = asyncio.run(client._resolve_cloud_api_key("ollama_cloud"))
        self.assertEqual(value, "ollama-cloud-secret")

    def test_resolve_cloud_api_key_applies_provider_miss_cooldown_after_404(self):
        requested_urls = []

        class _Resp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.content = b""

            def json(self):
                return {}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                requested_urls.append(url)
                return _Resp(404)

        env = {
            "INTERNAL_SECRET_RESOLVE_TOKEN": "tkn",
            "SECRETS_API_URL": "http://secrets.local/api/secrets/resolve",
            "OPENAI_API_KEY": "",
            "OPENAI_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()), \
             patch.object(client, "get_secret_resolve_miss_ttl_s", return_value=120), \
             patch.object(client, "get_secret_resolve_not_found_ttl_s", return_value=120):
            first = asyncio.run(client._resolve_cloud_api_key("openai"))
            second = asyncio.run(client._resolve_cloud_api_key("openai"))

        self.assertEqual(first, "")
        self.assertEqual(second, "")
        self.assertEqual(len(requested_urls), 2)

    def test_resolve_cloud_api_key_prefers_last_successful_secret_candidate(self):
        requested_names = []
        call_idx = {"value": 0}

        class _Resp:
            def __init__(self, status_code: int, payload=None):
                self.status_code = status_code
                self._payload = payload or {}
                self.content = b"{}"

            def json(self):
                return dict(self._payload)

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                name = str(url).rsplit("/", 1)[-1]
                requested_names.append(name)
                call_idx["value"] += 1
                if call_idx["value"] == 1 and name == "OPENAI_API_KEY":
                    return _Resp(404)
                if name == "OPENAI_KEY":
                    return _Resp(200, {"value": "live-key"})
                return _Resp(404)

        env = {
            "INTERNAL_SECRET_RESOLVE_TOKEN": "tkn",
            "SECRETS_API_URL": "http://secrets.local/api/secrets/resolve",
            "OPENAI_API_KEY": "",
            "OPENAI_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()), \
             patch.object(client, "get_secret_resolve_miss_ttl_s", return_value=0), \
             patch.object(client, "get_secret_resolve_not_found_ttl_s", return_value=0):
            first = asyncio.run(client._resolve_cloud_api_key("openai"))
            client._API_KEY_CACHE.clear()
            second = asyncio.run(client._resolve_cloud_api_key("openai"))

        self.assertEqual(first, "live-key")
        self.assertEqual(second, "live-key")
        self.assertEqual(requested_names[:2], ["OPENAI_API_KEY", "OPENAI_KEY"])
        self.assertEqual(requested_names[2], "OPENAI_KEY")

    def test_capture_rate_limit_headers_updates_snapshot(self):
        headers = {
            "x-ratelimit-limit-requests": "1000",
            "x-ratelimit-remaining-requests": "777",
            "x-ratelimit-limit-tokens": "200000",
            "x-ratelimit-remaining-tokens": "150000",
            "x-request-id": "req-123",
        }
        client._capture_rate_limit_headers("openai", headers, 200)
        snap = client.get_rate_limit_snapshot()
        self.assertIn("openai", snap)
        self.assertEqual(snap["openai"]["request_limit"], 1000)
        self.assertEqual(snap["openai"]["request_remaining"], 777)
        self.assertEqual(snap["openai"]["token_limit"], 200000)
        self.assertEqual(snap["openai"]["token_remaining"], 150000)

    def test_capture_rate_limit_headers_accepts_alt_header_names_and_structured_values(self):
        headers = {
            "x-ratelimit-requests-limit": "1200;w=60",
            "x-ratelimit-requests-remaining": "1100;w=60",
            "x-ratelimit-tokens-limit": "250000;w=60",
            "x-ratelimit-tokens-remaining": "249000;w=60",
            "x-ratelimit-requests-reset": "59",
            "x-request-id": "req-structured",
        }
        client._capture_rate_limit_headers("ollama_cloud", headers, 200)
        snap = client.get_rate_limit_snapshot()
        self.assertIn("ollama_cloud", snap)
        self.assertEqual(snap["ollama_cloud"]["request_limit"], 1200)
        self.assertEqual(snap["ollama_cloud"]["request_remaining"], 1100)
        self.assertEqual(snap["ollama_cloud"]["token_limit"], 250000)
        self.assertEqual(snap["ollama_cloud"]["token_remaining"], 249000)

    def test_complete_prompt_ollama_cloud_uses_chat_endpoint(self):
        called = {}

        class _Resp:
            status_code = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield '{"message":{"content":"ok-"},"done":false}'
                yield '{"message":{"content":"cloud"},"done":true}'

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json=None, headers=None):
                called["method"] = method
                called["url"] = url
                called["json"] = json or {}
                called["headers"] = headers or {}
                return _Resp()

        with patch.object(client, "_resolve_cloud_api_key", return_value="x"), \
             patch.object(client, "_ollama_cloud_base", return_value="https://ollama.example"), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()):
            out = asyncio.run(
                client.complete_prompt(
                    provider="ollama_cloud",
                    model="deepseek-v3.1:671b",
                    prompt="hello",
                    timeout_s=5,
                    ollama_endpoint="http://ignored:11434",
                    json_mode=True,
                )
            )

        self.assertEqual(out, "ok-cloud")
        self.assertEqual(called["url"], "https://ollama.example/api/chat")
        self.assertIn("messages", called["json"])
        self.assertNotIn("prompt", called["json"])

    def test_stream_prompt_ollama_cloud_uses_chat_endpoint(self):
        called = {}

        class _StreamResp:
            status_code = 200
            headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                return None

            async def aiter_lines(self):
                yield '{"message":{"content":"A"}}'
                yield '{"message":{"content":"B"},"done":true}'

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json=None, headers=None):
                called["method"] = method
                called["url"] = url
                called["json"] = json or {}
                called["headers"] = headers or {}
                return _StreamResp()

        async def _collect() -> str:
            parts = []
            async for chunk in client.stream_prompt(
                provider="ollama_cloud",
                model="deepseek-v3.1:671b",
                prompt="hello",
                timeout_s=5,
                ollama_endpoint="http://ignored:11434",
            ):
                parts.append(chunk)
            return "".join(parts)

        with patch.object(client, "_resolve_cloud_api_key", return_value="x"), \
             patch.object(client, "_ollama_cloud_base", return_value="https://ollama.example"), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()):
            out = asyncio.run(_collect())

        self.assertEqual(out, "AB")
        self.assertEqual(called["url"], "https://ollama.example/api/chat")
        self.assertIn("messages", called["json"])
        self.assertNotIn("prompt", called["json"])

    def test_complete_prompt_ollama_cloud_prefers_output_model_for_cross_provider_name(self):
        calls = []

        class _Resp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                if self.status_code >= 400:
                    req = client.httpx.Request("POST", "https://ollama.example/api/chat")
                    resp = client.httpx.Response(self.status_code, request=req)
                    raise client.httpx.HTTPStatusError("boom", request=req, response=resp)
                return None

            async def aiter_lines(self):
                yield '{"message":{"content":"fallback-ok"},"done":true}'

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json=None, headers=None):
                payload = json or {}
                calls.append(str(payload.get("model") or ""))
                status = 404 if payload.get("model") == "gpt-4.1" else 200
                return _Resp(status)

        with patch.object(client, "_resolve_cloud_api_key", return_value="x"), \
             patch.object(client, "_ollama_cloud_base", return_value="https://ollama.example"), \
             patch.object(client, "get_output_model", return_value="deepseek-v3.1:671b"), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()):
            out = asyncio.run(
                client.complete_prompt(
                    provider="ollama_cloud",
                    model="gpt-4.1",
                    prompt="hello",
                    timeout_s=5,
                    ollama_endpoint="http://ignored:11434",
                    json_mode=True,
                )
            )

        self.assertEqual(out, "fallback-ok")
        self.assertEqual(calls, ["deepseek-v3.1:671b"])

    def test_complete_chat_ollama_cloud_falls_back_on_404(self):
        calls = []

        class _Resp:
            def __init__(self, status_code: int, payload=None):
                self.status_code = status_code
                self.headers = {}
                self._payload = payload or {}

            def raise_for_status(self):
                if self.status_code >= 400:
                    req = client.httpx.Request("POST", "https://ollama.example/api/chat")
                    resp = client.httpx.Response(self.status_code, request=req)
                    raise client.httpx.HTTPStatusError("boom", request=req, response=resp)
                return None

            def json(self):
                return self._payload

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url, json=None, headers=None):
                payload = json or {}
                model = str(payload.get("model") or "")
                calls.append(model)
                if model == "deepseek-v3.1:671b":
                    return _Resp(404)
                return _Resp(
                    200,
                    payload={
                        "message": {
                            "content": "chat-fallback-ok",
                            "tool_calls": [],
                        }
                    },
                )

        with patch.object(client, "_resolve_cloud_api_key", return_value="x"), \
             patch.object(client, "_ollama_cloud_base", return_value="https://ollama.example"), \
             patch.object(client, "get_output_model", return_value="deepseek-v3.1:671b"), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()):
            out = asyncio.run(
                client.complete_chat(
                    provider="ollama_cloud",
                    model="gpt-4.1",
                    messages=[{"role": "user", "content": "hello"}],
                    timeout_s=5,
                    ollama_endpoint="http://ignored:11434",
                )
            )

        self.assertEqual(out.get("content"), "chat-fallback-ok")
        self.assertEqual(calls, ["deepseek-v3.1:671b", "gpt-4.1"])

    def test_stream_chat_ollama_cloud_falls_back_on_404(self):
        calls = []

        class _Resp:
            def __init__(self, status_code: int):
                self.status_code = status_code
                self.headers = {}

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def raise_for_status(self):
                if self.status_code >= 400:
                    req = client.httpx.Request("POST", "https://ollama.example/api/chat")
                    resp = client.httpx.Response(self.status_code, request=req)
                    raise client.httpx.HTTPStatusError("boom", request=req, response=resp)
                return None

            async def aiter_lines(self):
                yield '{"message":{"content":"chat-"},"done":false}'
                yield '{"message":{"content":"stream"},"done":true}'

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def stream(self, method, url, json=None, headers=None):
                payload = json or {}
                model = str(payload.get("model") or "")
                calls.append(model)
                if model == "deepseek-v3.1:671b":
                    return _Resp(404)
                return _Resp(200)

        async def _collect() -> str:
            parts = []
            async for chunk in client.stream_chat(
                provider="ollama_cloud",
                model="gpt-4.1",
                messages=[{"role": "user", "content": "hello"}],
                timeout_s=5,
                ollama_endpoint="http://ignored:11434",
            ):
                parts.append(chunk)
            return "".join(parts)

        with patch.object(client, "_resolve_cloud_api_key", return_value="x"), \
             patch.object(client, "_ollama_cloud_base", return_value="https://ollama.example"), \
             patch.object(client, "get_output_model", return_value="deepseek-v3.1:671b"), \
             patch.object(client.httpx, "AsyncClient", return_value=_Client()):
            out = asyncio.run(_collect())

        self.assertEqual(out, "chat-stream")
        self.assertEqual(calls, ["deepseek-v3.1:671b", "gpt-4.1"])


if __name__ == "__main__":
    unittest.main()
