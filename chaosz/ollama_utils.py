import json
import shutil
import subprocess
import urllib.request
import urllib.error
import os


def _context_from_modelinfo(modelinfo: dict) -> int:
    """Return the advertised native context length from an Ollama model card."""
    for key, value in modelinfo.items():
        if key.endswith(".context_length"):
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return 8192


def context_window_options(native_context: int) -> list[int]:
    """Return selectable context sizes: native maximum, then powers of two to 8K."""
    native_context = max(int(native_context or 8192), 1)
    if native_context <= 8192:
        return [native_context]
    options = [native_context]
    value = 1 << (native_context.bit_length() - 1)
    if value == native_context:
        value //= 2
    while value >= 8192:
        options.append(value)
        value //= 2
    return options


def format_context_window(tokens: int) -> str:
    """Format a context size compactly for menus and diagnostics."""
    if tokens >= 1_000_000:
        return f"{tokens // 1_000_000}M"
    if tokens >= 1000:
        return f"{tokens // 1000}K"
    return str(tokens)


def derive_model_profile(model_name: str, modelinfo: dict, capabilities: list | None = None,
                         model_size_bytes: int = 0) -> dict:
    """Create safe local runtime defaults from Ollama metadata.

    The advertised context window is a model capability, not a good default for
    a local machine.  Keep the two values separate so the UI and requests use a
    modest runtime budget while retaining the native maximum as information.
    """
    architecture = str(modelinfo.get("general.architecture", "")).lower()
    lower_name = model_name.lower()
    caps = {str(item).lower() for item in (capabilities or [])}
    is_qwen = architecture.startswith("qwen") or "qwen" in lower_name
    is_gpt_oss = "gpt-oss" in lower_name or architecture.startswith("gptoss")
    native_context = _context_from_modelinfo(modelinfo)

    # Qwen and GPT-OSS have useful reasoning/tool support, but their long
    # native windows are unsuitable as an automatic local default.
    if is_qwen or is_gpt_oss:
        runtime_context, max_output, profile_name = 16384, 8192, "reasoning"
    else:
        runtime_context, max_output, profile_name = 8192, 4096, "balanced"

    # Do not reserve more KV cache than the model can support.  A large model on
    # a memory-constrained host gets the safer 8K starting point.
    runtime_context = min(runtime_context, native_context)
    available_bytes = 0
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        available_bytes = page_size * available_pages
    except (AttributeError, OSError, ValueError):
        pass
    if model_size_bytes and available_bytes and available_bytes < model_size_bytes + 8 * 1024**3:
        runtime_context = min(runtime_context, 8192)

    return {
        "architecture": architecture or "unknown",
        "capabilities": sorted(caps),
        "native_context_window": native_context,
        "context_window": runtime_context,
        "max_output_tokens": max_output,
        "profile": profile_name,
        "thinking_supported": "thinking" in caps or is_qwen or is_gpt_oss,
        "tools_supported": "tools" in caps,
        "vision_supported": "vision" in caps,
    }


def get_model_profile(model_name: str) -> dict:
    """Fetch Ollama metadata and derive a safe runtime profile.

    Fail closed to generic local defaults so an unavailable daemon never causes
    an advertised 256K+ context window to become the runtime setting.
    """
    data: dict = {}
    try:
        body = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/show", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception:
        pass

    model_size = 0
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            tags = json.loads(resp.read().decode()).get("models", [])
        matched = next((item for item in tags if item.get("name") == model_name), {})
        model_size = int(matched.get("size") or 0)
    except Exception:
        pass

    return derive_model_profile(
        model_name,
        data.get("modelinfo") or data.get("model_info") or {},
        data.get("capabilities") or [],
        model_size,
    )


def apply_model_profile(provider_data: dict, model_name: str) -> dict:
    """Merge fresh automatic defaults without overwriting explicit user choices."""
    profile = get_model_profile(model_name)
    provider_data["native_context_window"] = profile["native_context_window"]
    provider_data["model_profile"] = profile["profile"]
    provider_data["model_architecture"] = profile["architecture"]
    provider_data["model_capabilities"] = profile["capabilities"]
    overrides = provider_data.get("context_window_overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        provider_data["context_window_overrides"] = overrides
    override = overrides.get(model_name)
    if isinstance(override, int) and 0 < override <= profile["native_context_window"]:
        provider_data["context_window"] = override
    else:
        provider_data["context_window"] = profile["context_window"]
    if not provider_data.get("max_output_tokens_user_override"):
        provider_data["max_output_tokens"] = profile["max_output_tokens"]
    if "temperature" not in provider_data:
        # Qwen's non-thinking recommendation; /reason on can later use its
        # own model-native default without clobbering a selected temperature.
        provider_data["temperature"] = 0.7
    return profile


def get_loaded_model_context(model_name: str) -> int | None:
    """Return a loaded model's active context size, if Ollama reports one."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with urllib.request.urlopen(req, timeout=3) as resp:
            models = json.loads(resp.read().decode()).get("models", [])
        for model in models:
            if model.get("name") == model_name or model.get("model") == model_name:
                context = model.get("context_length")
                return int(context) if context else None
    except Exception:
        pass
    return None


def unload_model(model_name: str) -> bool:
    """Ask Ollama to release a loaded model so its next request can reconfigure it."""
    try:
        body = json.dumps({"model": model_name, "keep_alive": 0}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate", data=body,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception:
        return False


def ensure_runtime_context(model_name: str, desired_context: int) -> bool:
    """Unload only when an existing runner has a conflicting context size.

    Ollama applies ``num_ctx`` when it loads a runner, not per request. Without
    this guard, a prior 262K session can silently defeat a later safe 8K
    profile, consume tens of GB, and make normal tool calls appear hung.
    """
    active_context = get_loaded_model_context(model_name)
    if active_context is None or active_context == desired_context:
        return False
    return unload_model(model_name)


def is_ollama_installed() -> bool:
    return shutil.which("ollama") is not None


def install_ollama() -> tuple[bool, str]:
    """Run the official Ollama install one-liner. Linux only. Timeout: 120s."""
    try:
        proc = subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode == 0:
            return True, ""
        return False, proc.stderr.strip() or f"Exit code {proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Installation timed out after 120 seconds."
    except Exception as e:
        return False, str(e)


def get_running_models() -> list[str]:
    """Return list of locally available model names. Returns [] on any error."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def is_model_available_online(model_name: str) -> tuple[bool, str]:
    """Check if model exists on ollama.com/library. Returns (True, '') or (False, reason)."""
    url = f"https://ollama.com/library/{model_name}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True, ""
            return False, f"Unexpected status {resp.status}"
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "Model not found on ollama.com"
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


def get_free_disk_gb() -> float:
    """Return free disk space in GB for the filesystem containing ~/.ollama (or /)."""
    ollama_dir = os.path.expanduser("~/.ollama")
    check_path = ollama_dir if os.path.exists(ollama_dir) else "/"
    usage = shutil.disk_usage(check_path)
    return usage.free / 1_000_000_000


def pull_model(model_name: str, progress_callback=None) -> tuple[bool, str]:
    """Pull model via Ollama REST API. Streams NDJSON progress. Timeout: 600s per read."""
    body = json.dumps({"name": model_name, "stream": True}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/pull",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if progress_callback is not None:
                    try:
                        progress_callback(line)
                    except Exception:
                        pass
                try:
                    obj = json.loads(line)
                    if obj.get("error"):
                        return False, obj["error"]
                except Exception:
                    pass
        return True, ""
    except Exception as e:
        return False, str(e)


def delete_model(model_name: str) -> tuple[bool, str]:
    """Delete a local model via `ollama rm`. Timeout: 30s."""
    try:
        proc = subprocess.run(
            ["ollama", "rm", model_name],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return True, ""
        return False, proc.stderr.strip() or f"Exit code {proc.returncode}"
    except subprocess.TimeoutExpired:
        return False, "Deletion timed out after 30 seconds."
    except FileNotFoundError:
        return False, "ollama binary not found."
    except Exception as e:
        return False, str(e)


def get_model_context_window(model_name: str) -> int:
    """Query ollama for context window size. Returns 8192 on any error."""
    try:
        body = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/show",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        modelinfo = data.get("modelinfo") or data.get("model_info", {})
        return _context_from_modelinfo(modelinfo)
    except Exception:
        return 8192
