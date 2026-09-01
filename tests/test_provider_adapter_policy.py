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

    class _DummyAPIError(Exception):
        pass

    class _DummyRateLimitError(Exception):
        pass

    openai_stub.OpenAI = _DummyOpenAI
    openai_stub.AuthenticationError = _DummyAuthError
    openai_stub.APIError = _DummyAPIError
    openai_stub.RateLimitError = _DummyRateLimitError
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
    prepare_messages_for_ollama,
    sync_runtime_provider_state,
    validate_provider_key,
)
from chaosz.ollama_utils import apply_model_profile, context_window_options, derive_model_profile, format_context_window
from chaosz.state import state
from chaosz.stream_adapters import (
    OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS,
    _iter_ollama,
    _ollama_needs_prompt_think_tag,
    _ollama_think_value,
)
from chaosz.ui.app_ai_turn import (
    MAX_TRUNCATION_TOOL_ACTION_NUDGES,
    _build_truncation_tool_action_prompt,
    _build_verification_prompt,
    _build_failed_verification_recovery_message,
    _incomplete_task_advice,
    _output_limit_advice,
    _timeout_advice,
    _file_edit_recovery_message,
    _is_verifiable_code_change,
    _is_verification_command,
    _is_file_edit_search_miss,
    _is_verification_blocked_after_failure,
    _tool_error_fingerprint,
    request_cancel,
)


class ProviderAdapterPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        state.reasoning.enabled = False
        state.provider.active = "deepseek"
        state.provider.model = "deepseek-v4-flash"
        state.provider.max_ctx = 128000
        state.provider.max_output_tokens = 8192
        state.provider.temperature = 0.7
        state.session.id = "test-session"
        state.ui.cancel_requested = False

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
        self.assertIs(_ollama_think_value("qwen3:latest", False), False)
        self.assertTrue(_ollama_needs_prompt_think_tag("gemma3:12b"))
        self.assertFalse(_ollama_needs_prompt_think_tag("qwen3:latest"))

    def test_prepare_ollama_messages_uses_tool_name_when_native_call_has_no_id(self) -> None:
        prepared = prepare_messages_for_ollama([
            {"role": "user", "content": "Write a file."},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "",
                    "type": "function",
                    "function": {"name": "file_write", "arguments": '{"path": "a.py"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "", "content": "File written."},
        ])

        call = prepared[1]["tool_calls"][0]
        self.assertEqual(prepared[1]["content"], "")
        self.assertNotIn("id", call)
        self.assertEqual(call["function"]["arguments"], {"path": "a.py"})
        self.assertEqual(prepared[2]["tool_name"], "file_write")
        self.assertNotIn("tool_call_id", prepared[2])

    def test_qwen_profile_uses_safe_runtime_limits_not_native_maximum(self) -> None:
        profile = derive_model_profile(
            "qwen3.8:27b-q4_K_M",
            {"general.architecture": "qwen35", "qwen35.context_length": 262144},
            ["completion", "vision", "tools", "thinking"],
        )

        self.assertEqual(profile["native_context_window"], 262144)
        self.assertLessEqual(profile["context_window"], 16384)
        self.assertEqual(profile["max_output_tokens"], 8192)
        self.assertTrue(profile["thinking_supported"])
        self.assertTrue(profile["tools_supported"])
        self.assertTrue(profile["vision_supported"])

    def test_context_window_options_include_native_maximum_and_halve_to_8k(self) -> None:
        self.assertEqual(context_window_options(1_000_000), [1_000_000, 524288, 262144, 131072, 65536, 32768, 16384, 8192])
        self.assertEqual(context_window_options(65536), [65536, 32768, 16384, 8192])
        self.assertEqual(context_window_options(4096), [4096])
        self.assertEqual(format_context_window(1_000_000), "1M")
        self.assertEqual(format_context_window(32768), "32K")

    def test_model_scoped_context_override_does_not_leak_to_another_model(self) -> None:
        profile = {
            "native_context_window": 262144,
            "context_window": 8192,
            "max_output_tokens": 4096,
            "profile": "balanced",
            "architecture": "test",
            "capabilities": [],
        }
        data = {"context_window_overrides": {"gemma4:12b": 32768}}

        with patch("chaosz.ollama_utils.get_model_profile", return_value=profile):
            apply_model_profile(data, "gemma4:12b")
            self.assertEqual(data["context_window"], 32768)
            apply_model_profile(data, "another-model")

        self.assertEqual(data["context_window"], 8192)

    def test_sync_repairs_native_context_saved_as_runtime_context(self) -> None:
        providers = {
            "ollama": {
                "model": "qwen3.8:27b-q4_K_M",
                "local": True,
                "model_profile": "reasoning",
                "native_context_window": 262144,
                "context_window": 262144,
                "max_output_tokens": 8192,
            }
        }

        def apply_safe_profile(data: dict, _model: str) -> dict:
            data["context_window"] = 8192
            data["max_output_tokens"] = 8192
            return {}

        with (
            patch("chaosz.providers.load_providers", return_value=(providers, "ollama")),
            patch("chaosz.providers.save_providers"),
            patch("chaosz.ollama_utils.apply_model_profile", side_effect=apply_safe_profile) as apply_profile,
        ):
            sync_runtime_provider_state("ollama", providers)

        apply_profile.assert_called_once_with(providers["ollama"], "qwen3.8:27b-q4_K_M")
        self.assertEqual(state.provider.max_ctx, 8192)

    def test_sync_migrates_legacy_context_override_to_its_current_model(self) -> None:
        providers = {
            "ollama": {
                "model": "gemma4:12b",
                "local": True,
                "model_profile": "balanced",
                "context_window": 32768,
                "context_window_user_override": True,
            }
        }

        with (
            patch("chaosz.providers.load_providers", return_value=(providers, "ollama")),
            patch("chaosz.providers.save_providers") as save,
        ):
            sync_runtime_provider_state("ollama", providers)

        self.assertEqual(providers["ollama"]["context_window_overrides"], {"gemma4:12b": 32768})
        self.assertNotIn("context_window_user_override", providers["ollama"])
        save.assert_called_once()

    def test_ollama_request_sends_runtime_limits_and_explicitly_disables_thinking(self) -> None:
        captured: dict = {}

        class _FakeOllamaClient:
            def chat(self, **kwargs):
                captured.update(kwargs)
                return iter([{
                    "message": {"thinking": "leaked chain of thought", "content": "ok"},
                    "done_reason": "stop",
                    "done": True,
                }])

        state.provider.active = "ollama"
        state.provider.model = "qwen3.8:27b-q4_K_M"
        state.provider.max_ctx = 16384
        state.provider.max_output_tokens = 8192
        state.provider.temperature = 0.7
        state.reasoning.enabled = False

        with (
            patch("chaosz.providers.get_native_ollama_client", return_value=_FakeOllamaClient()),
            patch("chaosz.ollama_utils.ensure_runtime_context") as ensure_context,
        ):
            chunks = list(_iter_ollama([{"role": "user", "content": "hi"}], None, state.provider.model))

        ensure_context.assert_called_once_with("qwen3.8:27b-q4_K_M", 16384)
        self.assertIs(captured["think"], False)
        self.assertEqual(captured["options"]["num_ctx"], 16384)
        self.assertEqual(captured["options"]["num_predict"], 8192)
        self.assertNotIn("leaked chain of thought", [chunk.reasoning_line for chunk in chunks])
        self.assertIn("ok", [chunk.text for chunk in chunks])

    def test_cancel_request_is_idempotent(self) -> None:
        self.assertTrue(request_cancel())
        self.assertFalse(request_cancel())

    def test_ollama_tool_call_has_no_automatic_idle_cancellation(self) -> None:
        self.assertIsNone(OLLAMA_STREAM_IDLE_TIMEOUT_SECONDS)

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

    def test_file_edit_search_miss_gets_a_read_first_recovery_instruction(self) -> None:
        result = "Edit failed: Found 0 matches for SEARCH block."

        self.assertTrue(_is_file_edit_search_miss("file_edit", "error", result))
        self.assertFalse(_is_file_edit_search_miss("file_write", "error", result))
        self.assertFalse(_is_file_edit_search_miss("file_edit", "ok", result))

        message = _file_edit_recovery_message("pyproject.toml")
        self.assertIn("file_read for 'pyproject.toml'", message)
        self.assertIn("Do NOT repeat this patch", message)

    def test_error_fingerprint_distinguishes_different_file_edit_patches(self) -> None:
        first = _tool_error_fingerprint(
            "file_edit",
            {"path": "main.py", "edits": [{"search": "old one", "replace": "new one"}]},
        )
        second = _tool_error_fingerprint(
            "file_edit",
            {"path": "main.py", "edits": [{"search": "old two", "replace": "new two"}]},
        )
        self.assertNotEqual(first, second)

    def test_error_fingerprint_detects_the_same_file_edit_patch(self) -> None:
        args = {"path": "main.py", "edits": [{"search": "old", "replace": "new"}]}
        self.assertEqual(
            _tool_error_fingerprint("file_edit", args),
            _tool_error_fingerprint("file_edit", dict(args)),
        )

    def test_code_changes_require_a_real_verification_command(self) -> None:
        self.assertTrue(_is_verifiable_code_change("file_write", {"path": "app/main.py"}))
        self.assertTrue(_is_verifiable_code_change("file_edit", {"path": "ui.tsx"}))
        self.assertFalse(_is_verifiable_code_change("file_write", {"path": "README.md"}))
        self.assertFalse(_is_verifiable_code_change("file_read", {"path": "main.py"}))
        self.assertTrue(_is_verification_command("uv run python -m py_compile app/main.py"))

    def test_failed_verification_recovery_requires_a_source_change_first(self) -> None:
        command = "uv run python main.py"
        message = _build_failed_verification_recovery_message(command)
        self.assertIn("VERIFICATION BLOCKED", message)
        self.assertIn("Do NOT run another test", message)
        self.assertIn(command, message)

    def test_failed_verification_blocks_different_test_command_variants(self) -> None:
        self.assertTrue(_is_verification_blocked_after_failure(
            True,
            "shell_exec",
            {"command": "QT_QPA_PLATFORM=offscreen uv run python main.py"},
        ))
        self.assertFalse(_is_verification_blocked_after_failure(
            False,
            "shell_exec",
            {"command": "uv run python main.py"},
        ))
        self.assertFalse(_is_verification_blocked_after_failure(
            True,
            "file_edit",
            {"path": "main.py"},
        ))
        self.assertTrue(_is_verification_command("cargo test"))
        self.assertFalse(_is_verification_command("ls -la"))
        self.assertIn("VERIFICATION PASS REQUIRED", _build_verification_prompt())
        self.assertIn("failed", _build_verification_prompt(True))

    def test_truncation_recovery_requires_a_tool_action_not_progress_prose(self) -> None:
        message = _build_truncation_tool_action_prompt(0)
        final_attempt = _build_truncation_tool_action_prompt(MAX_TRUNCATION_TOOL_ACTION_NUDGES)

        self.assertIn("MUST contain one appropriate tool call", message)
        self.assertIn("Do not reply with a plan, progress update", message)
        self.assertIn("final recovery attempt", final_attempt)

    def test_failure_advice_distinguishes_output_from_context_and_ollama_timeout(self) -> None:
        state.provider.active = "ollama"
        state.provider.max_output_tokens = 8192

        self.assertIn("not context exhaustion", _output_limit_advice())
        self.assertIn("/context", _timeout_advice())
        self.assertIn("Earlier tool changes were kept", _incomplete_task_advice())


if __name__ == "__main__":
    unittest.main()
