import json
import shutil
import subprocess
import urllib.request
import urllib.error
import os


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
        for key in (
            "llama.context_length",
            "gemma4.context_length",
            "gemma.context_length",
            "mistral.context_length",
            "qwen2.context_length",
            "qwen3.context_length",
            "qwen2_5.context_length",
        ):
            if key in modelinfo:
                return int(modelinfo[key])
        # Generic fallback: any architecture key ending in .context_length
        for key, value in modelinfo.items():
            if key.endswith(".context_length"):
                return int(value)
        return 8192
    except Exception:
        return 8192
