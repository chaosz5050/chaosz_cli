import os

from openai import OpenAI, AuthenticationError
import ollama

from chaosz.config import _read_config_file, _write_config_file

PROVIDER_REGISTRY = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model":    "deepseek-v4-flash",
        "reasoning_model": "deepseek-v4-pro",
        "context_window": 1000000,
        "max_output_tokens": 8192,
        "reasoning_max_output_tokens": 32768,
        "no_sampling_params": False,
        "supports_thinking": True,
    },
    "kimi": {
        "base_url": "https://api.moonshot.ai/v1",
        "model":    "kimi-k2.5",
        "context_window": 256000,
        "max_output_tokens": 8192,
        "no_sampling_params": True,   # Kimi rejects temperature/top_p
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "model":    "gemini-2.5-flash",
        "context_window": 1000000,
        "max_output_tokens": 65536,
        "no_sampling_params": False,
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "model":    "mistral-large-latest",
        "context_window": 32000,
        "max_output_tokens": 8192,
        "no_sampling_params": False,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model":    "",               # set at setup time
        "context_window": 8192,
        "max_output_tokens": 4096,
        "no_sampling_params": False,
        "local": True,                # no API key required
    },
}


def migrate_legacy_key(data: dict) -> dict:
    """Move flat api_key → providers.deepseek.api_key if old format detected."""
    if "api_key" in data and "providers" not in data:
        old_key = data.pop("api_key")
        defaults = PROVIDER_REGISTRY["deepseek"]
        data["providers"] = {
            "deepseek": {
                "api_key":            old_key,
                "base_url":           defaults["base_url"],
                "model":              defaults["model"],
                "context_window":     defaults["context_window"],
                "max_output_tokens":  defaults["max_output_tokens"],
            }
        }
        data.setdefault("active_provider", "deepseek")
    return data


def load_providers() -> tuple[dict, str]:
    """Load providers dict and active provider from project config.json.
    Runs migration if the old flat api_key format is detected.
    Returns (providers_dict, active_provider_name).
    """
    data = _read_config_file()
    if "api_key" in data and "providers" not in data:
        data = migrate_legacy_key(data)
        _write_config_file(data)
    providers = data.get("providers", {})
    active = data.get("active_provider", "deepseek")
    # DEEPSEEK_API_KEY env var always overrides stored key
    env_key = os.getenv("DEEPSEEK_API_KEY")
    if env_key:
        if "deepseek" not in providers:
            d = PROVIDER_REGISTRY["deepseek"]
            providers["deepseek"] = {
                "api_key": env_key, "base_url": d["base_url"],
                "model": d["model"], "context_window": d["context_window"],
            }
        else:
            providers["deepseek"]["api_key"] = env_key
    return providers, active


def save_providers(providers: dict, active_provider: str) -> None:
    """Persist providers dict and active_provider to project config.json."""
    data = _read_config_file()
    data["providers"] = providers
    data["active_provider"] = active_provider
    data.pop("api_key", None)   # remove legacy flat key if present
    _write_config_file(data)


def get_gemini_client():
    """Return an official Google Gemini client for the active provider."""
    providers, active = load_providers()
    pdata = providers.get("gemini")
    if not pdata or not pdata.get("api_key"):
        raise ValueError(
            "Gemini is not configured. Use /model add gemini."
        )
    from google import genai
    return genai.Client(api_key=pdata["api_key"])


def get_client() -> OpenAI:
    """Return an OpenAI-compatible client for the active provider."""
    providers, active = load_providers()
    pdata = providers.get(active)
    reg = PROVIDER_REGISTRY.get(active, {})
    if reg.get("local"):
        if not pdata:
            raise ValueError(
                f"Ollama is not configured. Use /model add ollama."
            )
        return OpenAI(api_key="ollama", base_url=pdata["base_url"])
    if not pdata or not pdata.get("api_key"):
        raise ValueError(
            f"No API key configured for '{active}'. Use /model add {active}."
        )
    return OpenAI(api_key=pdata["api_key"], base_url=pdata["base_url"])


def get_native_ollama_client() -> ollama.Client:
    """Return a native Ollama client for the active provider if local."""
    providers, active = load_providers()
    pdata = providers.get(active)
    reg = PROVIDER_REGISTRY.get(active, {})
    if not reg.get("local"):
        raise ValueError(f"Provider '{active}' is not a local Ollama provider.")
    if not pdata:
        raise ValueError(f"Ollama is not configured. Use /model add ollama.")
    # Extract host from base_url, e.g., "http://localhost:11434/v1" -> "http://localhost:11434"
    host = pdata["base_url"].replace("/v1", "")
    return ollama.Client(host=host)


def prepare_messages_for_ollama(messages: list) -> list:
    """Convert assistant tool_calls.function.arguments from JSON string to dict.
    The OpenAI format stores arguments as a JSON string; the Ollama native Python
    client's Pydantic model requires a dict.  Call this before ollama_client.chat().
    """
    import json as _json
    result = []
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            new_tcs = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = _json.loads(args)
                    except _json.JSONDecodeError:
                        args = {}
                new_tcs.append({**tc, "function": {**fn, "arguments": args}})
            result.append({**msg, "tool_calls": new_tcs})
        else:
            result.append(msg)
    return result


def build_api_params(provider_name: str, model: str, messages: list, tools: list | None = None) -> dict:
    """Build kwargs for client.chat.completions.create().
    Omits temperature/top_p for providers that reject them (e.g. Kimi).
    When tools is None, omits tools and tool_choice entirely.
    Callers may override stream or add timeout on the returned dict.
    """
    from chaosz.state import state
    params: dict = {
        "model":     model,
        "messages":  messages,
        "stream":    True,
        "max_tokens": state.provider.max_output_tokens,
    }
    # Enable usage tracking in the stream for OpenAI-compatible providers (DeepSeek/Kimi/etc)
    if provider_name != "ollama":
        params["stream_options"] = {"include_usage": True}

    if tools is not None:
        params["tools"] = tools
        params["tool_choice"] = "auto"

    # Moonshot (Kimi) specific caching
    if provider_name == "kimi":
        params["extra_body"] = {"prompt_cache_key": state.session.id}

    # no_sampling_params providers (Kimi) must not receive temperature or top_p
    registry_entry = PROVIDER_REGISTRY.get(provider_name, {})
    if not registry_entry.get("no_sampling_params"):
        params["temperature"] = state.provider.temperature

    # DeepSeek V4 thinking mode — ON by default, must be explicitly disabled when not reasoning.
    # Temperature and other sampling params are forbidden when thinking is enabled.
    if provider_name == "deepseek" and registry_entry.get("supports_thinking"):
        thinking_type = "enabled" if state.reasoning.enabled else "disabled"
        params.setdefault("extra_body", {})["thinking"] = {"type": thinking_type}
        if state.reasoning.enabled:
            params.pop("temperature", None)   # unsupported in thinking mode
            reasoning_out = registry_entry.get("reasoning_max_output_tokens")
            if reasoning_out:
                params["max_tokens"] = reasoning_out

    return params


def get_available_models(provider: str) -> list[str]:
    """Fetch available text/chat models from the provider's API.
    Returns a sorted list of model IDs/names.
    """
    if provider == "ollama":
        import urllib.request as _urllib_req
        import json as _json
        try:
            with _urllib_req.urlopen("http://localhost:11434/api/tags", timeout=3) as resp:
                data = _json.loads(resp.read().decode())
                return sorted([m["name"] for m in data.get("models", [])])
        except Exception:
            return []

    if provider == "gemini":
        client = get_gemini_client()
        models = []
        for m in client.models.list():
            name = m.name
            if name.startswith("models/"):
                name = name[len("models/"):]
            # Filter for text-generation models
            if any(kw in name.lower() for kw in ("gemini", "gemma", "pro", "flash", "ultra")):
                models.append(name)
        return sorted(models)

    # OpenAI-compatible providers (DeepSeek, Kimi)
    client = get_client()
    models = [m.id for m in client.models.list()]
    # Filter for text models: exclude embeddings, images, etc.
    text_models = [
        m for m in models
        if any(kw in m.lower() for kw in ("gpt", "chat", "reasoner", "deepseek", "kimi", "moonshot", "k2"))
        and not any(kw in m.lower() for kw in ("embedding", "dall-e", "whisper", "tts", "audit"))
    ]
    return sorted(text_models or models)


def validate_provider_key(provider: str, api_key: str) -> tuple[bool, str]:
    """Verify an API key with a cheap models.list() call.
    For local providers (Ollama), checks connectivity instead of an API key.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    defaults = PROVIDER_REGISTRY.get(provider)
    if not defaults:
        return False, f"Unknown provider: {provider}"
    if defaults.get("local"):
        import urllib.request as _urllib_req
        try:
            _urllib_req.urlopen("http://localhost:11434/api/tags", timeout=3)
            return True, ""
        except Exception:
            return False, "Ollama is not running — start it with: ollama serve"
    try:
        client = OpenAI(api_key=api_key, base_url=defaults["base_url"])
        client.models.list()
        return True, ""
    except AuthenticationError:
        return False, "Authentication failed — invalid API key."
    except Exception as e:
        return False, f"Connection error: {e}"
