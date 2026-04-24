from __future__ import annotations

import copy
import sys
import types
import unittest
from unittest.mock import patch

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class _DummyOpenAI:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _DummyAuthError(Exception):
        pass

    openai_stub.OpenAI = _DummyOpenAI
    openai_stub.AuthenticationError = _DummyAuthError
    sys.modules["openai"] = openai_stub

if "ollama" not in sys.modules:
    ollama_stub = types.ModuleType("ollama")

    class _DummyOllamaClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    ollama_stub.Client = _DummyOllamaClient
    sys.modules["ollama"] = ollama_stub

from chaosz.providers import (
    build_api_params,
    prepare_messages_for_ollama,
    provider_requires_reasoning_echo,
    sync_runtime_provider_state,
    validate_provider_key,
)
from chaosz.state import state
from chaosz.stream_adapters import _ollama_needs_prompt_think_tag, _ollama_think_value


class ProviderAdapterPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        state.reasoning.enabled = False
        state.provider.active = "deepseek"
        state.provider.model = "deepseek-v4-flash"
        state.provider.max_ctx = 128000
        state.provider.max_output_tokens = 8192
        state.provider.temperature = 0.7
        state.session.id = "test-session"

    def test_build_api_params_deepseek_streaming_reasoning_disabled(self) -> None:
        params = build_api_params("deepseek", "deepseek-v4-flash", [{"role": "user", "content": "hi"}])

        self.assertTrue(params["stream"])
        self.assertEqual(params["stream_options"], {"include_usage": True})
        self.assertEqual(params["temperature"], 0.7)
        self.assertEqual(params["extra_body"]["thinking"], {"type": "disabled"})
        self.assertEqual(params["max_tokens"], 8192)

    def test_build_api_params_deepseek_non_stream_omits_stream_options(self) -> None:
        params = build_api_params(
            "deepseek",
            "deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
            stream=False,
        )

        self.assertFalse(params["stream"])
        self.assertNotIn("stream_options", params)

    def test_build_api_params_deepseek_reasoning_enabled_uses_reasoning_budget(self) -> None:
        state.reasoning.enabled = True

        params = build_api_params("deepseek", "deepseek-v4-flash", [{"role": "user", "content": "hi"}])

        self.assertNotIn("temperature", params)
        self.assertEqual(params["extra_body"]["thinking"], {"type": "enabled"})
        self.assertEqual(params["max_tokens"], 32768)

    def test_build_api_params_kimi_sets_cache_and_thinking_without_sampling_params(self) -> None:
        state.reasoning.enabled = True

        params = build_api_params("kimi", "kimi-k2.5", [{"role": "user", "content": "hi"}])

        self.assertEqual(params["extra_body"]["prompt_cache_key"], "test-session")
        self.assertEqual(params["extra_body"]["thinking"], {"type": "enabled"})
        self.assertNotIn("temperature", params)
        self.assertEqual(params["max_tokens"], 32768)

    def test_provider_requires_reasoning_echo_only_for_supported_providers(self) -> None:
        self.assertTrue(provider_requires_reasoning_echo("deepseek"))
        self.assertTrue(provider_requires_reasoning_echo("kimi"))
        self.assertFalse(provider_requires_reasoning_echo("mistral"))
        self.assertFalse(provider_requires_reasoning_echo("gemini"))

    def test_sync_runtime_provider_state_uses_stored_model_without_reasoning_swap(self) -> None:
        providers = {
            "deepseek": {
                "model": "deepseek-v4-flash",
                "context_window": 128000,
                "max_output_tokens": 8192,
                "temperature": 0.3,
            }
        }
        state.reasoning.enabled = True

        with patch("chaosz.providers.load_providers", return_value=(providers, "deepseek")):
            sync_runtime_provider_state("deepseek", providers)

        self.assertEqual(state.provider.active, "deepseek")
        self.assertEqual(state.provider.model, "deepseek-v4-flash")
        self.assertEqual(state.provider.max_ctx, 128000)
        self.assertEqual(state.provider.max_output_tokens, 32768)
        self.assertEqual(state.provider.temperature, 0.3)

    def test_prepare_messages_for_ollama_converts_tool_arguments_to_dict(self) -> None:
        messages = [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "file_read",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            }
        ]

        prepared = prepare_messages_for_ollama(copy.deepcopy(messages))

        self.assertEqual(prepared[0]["tool_calls"][0]["function"]["arguments"], {"path": "README.md"})

    def test_ollama_think_helpers_choose_safe_defaults(self) -> None:
        self.assertEqual(_ollama_think_value("gpt-oss:20b", True), "medium")
        self.assertIs(_ollama_think_value("qwen3:latest", True), True)
        self.assertIsNone(_ollama_think_value("qwen3:latest", False))
        self.assertTrue(_ollama_needs_prompt_think_tag("gemma3:12b"))
        self.assertFalse(_ollama_needs_prompt_think_tag("qwen3:latest"))

    def test_validate_provider_key_openai_compat_uses_chat_probe(self) -> None:
        captured: dict = {}

        class _FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return object()

        class _FakeChat:
            def __init__(self):
                self.completions = _FakeCompletions()

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                self.chat = _FakeChat()

        with patch("chaosz.providers.OpenAI", _FakeClient):
            ok, err = validate_provider_key("deepseek", "key")

        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(captured["model"], "deepseek-v4-flash")
        self.assertEqual(captured["messages"], [{"role": "user", "content": "ping"}])
        self.assertFalse(captured["stream"])
        self.assertEqual(captured["max_tokens"], 1)
        self.assertEqual(captured["temperature"], 0)
        self.assertEqual(captured["extra_body"], {"thinking": {"type": "disabled"}})

    def test_validate_provider_key_kimi_omits_sampling_params(self) -> None:
        captured: dict = {}

        class _FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return object()

        class _FakeChat:
            def __init__(self):
                self.completions = _FakeCompletions()

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                self.chat = _FakeChat()

        with patch("chaosz.providers.OpenAI", _FakeClient):
            ok, err = validate_provider_key("kimi", "key")

        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertNotIn("temperature", captured)
        self.assertEqual(captured["extra_body"], {"thinking": {"type": "disabled"}})

    def test_validate_provider_key_maps_model_missing_error(self) -> None:
        class _FakeCompletions:
            def create(self, **kwargs):
                raise Exception("404 model not found")

        class _FakeChat:
            def __init__(self):
                self.completions = _FakeCompletions()

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                self.chat = _FakeChat()

        with patch("chaosz.providers.OpenAI", _FakeClient):
            ok, err = validate_provider_key("mistral", "key")

        self.assertFalse(ok)
        self.assertIn("default model 'mistral-large-latest' is unavailable", err)

    def test_validate_provider_key_gemini_uses_native_client(self) -> None:
        fake_genai = types.ModuleType("genai")
        captured: dict = {}

        class _FakeModels:
            def generate_content(self, **kwargs):
                captured.update(kwargs)
                return object()

        class _FakeGeminiClient:
            def __init__(self, api_key):
                captured["api_key"] = api_key
                self.models = _FakeModels()

        fake_genai.Client = _FakeGeminiClient
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai

        with patch.dict(sys.modules, {"google": fake_google, "google.genai": fake_genai}):
            ok, err = validate_provider_key("gemini", "gem-key")

        self.assertTrue(ok)
        self.assertEqual(err, "")
        self.assertEqual(captured["api_key"], "gem-key")
        self.assertEqual(captured["model"], "gemini-2.5-flash")
        self.assertEqual(captured["contents"], "ping")
        self.assertEqual(captured["config"], {"max_output_tokens": 1})


if __name__ == "__main__":
    unittest.main()
