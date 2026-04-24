import threading

from rich.text import Text

from chaosz.ollama_utils import (
    get_free_disk_gb,
    get_model_context_window,
    install_ollama,
    is_model_available_online,
    is_ollama_installed,
    pull_model,
)
from chaosz.providers import load_providers, save_providers
from chaosz.state import state


def start_ollama_setup(app) -> None:
    """Launch the Ollama setup wizard in a background thread."""
    event = threading.Event()
    state.ollama_wizard.input_event = event

    def _wizard():
        # ---- helpers --------------------------------------------------------

        def _write(msg: str, style: str = "yellow") -> None:
            app.call_from_thread(app._write, "", Text(msg, style=style))

        def _prompt_user(step: str, message: str, label: str, status: str) -> None:
            """Write message, switch to OLLAMA_SETUP mode, block until input arrives."""
            event.clear()
            state.ollama_wizard.step = step

            def _ui():
                app._write("", Text(message, style="yellow"))
                app._set_input_label(label)
                app._set_status(status)
                state.ui.mode = "OLLAMA_SETUP"

            app.call_from_thread(_ui)
            event.wait()

        def _abort(msg: str = "Ollama setup cancelled.") -> None:
            _write(msg, style="dim")
            _reset_mode()

        def _reset_mode() -> None:
            def _ui():
                state.ui.mode = "CHAT"
                state.ollama_wizard.step = ""
                app._set_input_label("You: ")
                app._set_status("Ready")

            app.call_from_thread(_ui)

        # ---- STEP 1: check if Ollama is installed ---------------------------

        if not is_ollama_installed():
            _prompt_user(
                step="INSTALL_CONFIRM",
                message="Ollama is not installed.\nInstall it now? (yes/no)",
                label="[bold yellow] OLLAMA SETUP: [/bold yellow] ",
                status="Install Ollama? (yes/no)",
            )
            if state.ollama_wizard.input_answer != "yes":
                _abort()
                return

            # ---- STEP 2: install Ollama -------------------------------------

            _write("Installing Ollama... (this may take a minute)", style="cyan")
            ok, err = install_ollama()
            if not ok:
                _write(f"Installation failed: {err}", style="red")
                _reset_mode()
                return
            _write("Ollama installed successfully.", style="green")

        # ---- STEP 3: ask for model name ------------------------------------

        while True:
            _prompt_user(
                step="MODEL_NAME",
                message=(
                    "Enter the model name to use (e.g. llama3, mistral, phi3):\n"
                    "Browse available models at https://ollama.com/library"
                ),
                label="[bold yellow] MODEL NAME: [/bold yellow] ",
                status="Enter Ollama model name (e.g. llama3)",
            )
            model_name = state.ollama_wizard.input_answer.strip()
            if not model_name:
                # handle_ollama_setup_input already guards empty MODEL_NAME,
                # but be defensive in case something slips through
                continue

            # ---- STEP 4: validate model + disk space -----------------------

            _write(f"Checking {model_name} on ollama.com...", style="dim")
            found, err = is_model_available_online(model_name)
            if not found:
                _write(f"Model not found: {err}. Please try another name.", style="red")
                continue  # loop back to STEP 3

            free_gb = get_free_disk_gb()
            if free_gb < 2.0:
                _prompt_user(
                    step="DISK_CONFIRM",
                    message=(
                        f"Warning: low disk space ({free_gb:.1f} GB free).\n"
                        "Type 'yes' to continue anyway or 'no' to cancel."
                    ),
                    label="[bold yellow] LOW DISK (yes/no): [/bold yellow] ",
                    status=f"Low disk ({free_gb:.1f} GB free). Continue? (yes/no)",
                )
                if state.ollama_wizard.input_answer != "yes":
                    _abort()
                    return
            else:
                _write(f"Free disk space: {free_gb:.1f} GB. Proceeding with download...", style="dim")

            break  # model name is valid, disk check passed

        # ---- STEP 5: pull the model ----------------------------------------

        _write(f"Pulling {model_name}... (this may take a while)", style="cyan")

        def _start_download():
            state.ui.mode = "CHAT"
            app._set_input_label("You: ")
            app._set_status(f"Downloading {model_name}... please wait")
            app.query_one("#user-input").disabled = True

        app.call_from_thread(_start_download)

        def _progress(line: str) -> None:
            if not line.strip():
                return
            import json as _json
            try:
                obj = _json.loads(line)
                completed = obj.get("completed")
                total = obj.get("total")
                status_val = obj.get("status", "")
                if completed is not None and total and total > 0:
                    pct = completed / total * 100
                    msg = f"Downloading {model_name}: {pct:.1f}%"
                elif status_val:
                    msg = f"{model_name}: {status_val}"
                else:
                    msg = line[:80]
            except Exception:
                msg = line[:80]
            app.call_from_thread(app._set_status, msg)

        ok, err = pull_model(model_name, progress_callback=_progress)

        def _re_enable():
            app.query_one("#user-input").disabled = False

        app.call_from_thread(_re_enable)

        if not ok:
            _write(f"Pull failed: {err}", style="red")
            _reset_mode()
            return

        # ---- STEP 6: detect context window + save --------------------------

        ctx_window = get_model_context_window(model_name)
        providers, active = load_providers()
        providers["ollama"] = {
            "api_key": "ollama",
            "base_url": "http://localhost:11434/v1",
            "model": model_name,
            "context_window": ctx_window,
            "local": True,
        }
        save_providers(providers, active)

        ctx_label = f"{ctx_window // 1000}K" if ctx_window >= 1000 else str(ctx_window)
        _write(
            f"Ollama ready. Model: {model_name} | Context: {ctx_label} tokens",
            style="green",
        )
        _write("Switching to Ollama...", style="cyan")
        app.call_from_thread(app._confirm_model_switch, "ollama")
        _reset_mode()

    threading.Thread(target=_wizard, daemon=True).start()


def handle_ollama_setup_input(app, user_input: str) -> bool:
    """Handle user input during OLLAMA_SETUP mode. Called by _handle_mode_dispatch."""
    step = state.ollama_wizard.step

    if step == "MODEL_NAME" and not user_input.strip():
        # Empty model name — leave wizard waiting, let user try again
        return True

    if step == "MODEL_NAME":
        state.ollama_wizard.input_answer = user_input.strip()
    else:
        state.ollama_wizard.input_answer = user_input.strip().lower()

    if state.ollama_wizard.input_event is not None:
        state.ollama_wizard.input_event.set()

    return True
