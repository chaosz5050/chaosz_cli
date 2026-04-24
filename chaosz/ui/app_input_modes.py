import os
import threading

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from chaosz.config import save_config, save_input_history, save_personality, save_active_skill
from chaosz.providers import (
    PROVIDER_REGISTRY,
    load_providers,
    save_providers,
    sync_runtime_provider_state,
    validate_provider_key,
)
from chaosz.state import _permission_event, state
from chaosz.ui.commands import handle_command
from chaosz.ui.widgets import HistoryInput


def show_tool_permission_prompt(app, fname: str, summary: str, diff: str | None) -> None:
    """Show a selection menu for a destructive file operation."""
    from chaosz.ui.app_rendering import _PERMISSION_OPTIONS_FULL
    state.permissions.awaiting = True
    app._unmount_plasma()
    if diff:
        app._write("", Text(diff, style="dim"))
    app._write("", Text(f"Allow {fname}: {summary}?", style="yellow"))
    app._show_permission_display(_PERMISSION_OPTIONS_FULL, f"Allow {fname}?")


def prompt_working_dir(app) -> None:
    """Ask user to confirm or type a working directory."""
    cwd = os.getcwd()
    state.ui.mode = "WORKDIR_SET"
    app._unmount_plasma()
    app._write(
        "",
        Text(
            f"File operations need a working directory.\n"
            f"Press Enter to use: {cwd}\n"
            f"Or type an absolute path:",
            style="yellow",
        ),
    )
    app._set_input_label("[bold yellow] WORKDIR: [/bold yellow] ")
    app._set_status("Set working directory for file operations.")
    app.query_one("#user-input", HistoryInput).focus()


def process_permission_response(app, _response: str) -> None:
    """Handle menu selection when awaiting file operation confirmation."""
    if not state.permissions.awaiting:
        return
    idx = state.permissions.approval_index
    if idx == 0:  # Yes (once)
        state.permissions.granted = True
        state.permissions.file_session_granted = False
    elif idx == 1:  # Yes for session
        state.permissions.granted = True
        state.permissions.file_session_granted = True
    else:  # No
        state.permissions.granted = False
        state.permissions.file_session_granted = False
    state.permissions.awaiting = False
    app._hide_permission_display()
    app._mount_plasma()
    _permission_event.set()


def show_shell_permission_prompt(app, command: str, reason: str, always_prompt: bool) -> None:
    """Show selection menu for shell command permission."""
    from chaosz.ui.app_rendering import _PERMISSION_OPTIONS_FULL, _PERMISSION_OPTIONS_SHORT
    state.permissions.awaiting_shell = True
    app._unmount_plasma()
    if always_prompt:
        app._write("", Text("⚠ ALWAYS REQUIRES PERMISSION", style="bold red"))
    app._write("", Text(f"Command: {command}", style="yellow"))
    app._write("", Text(f"Reason: {reason}", style="dim"))
    options = _PERMISSION_OPTIONS_SHORT if always_prompt else _PERMISSION_OPTIONS_FULL
    app._show_permission_display(options, "Allow shell command?")


def process_shell_permission_response(app, _response: str) -> None:
    """Handle menu selection when awaiting shell permission."""
    if not state.permissions.awaiting_shell:
        return
    idx = state.permissions.approval_index
    n = state.permissions.approval_option_count
    if n == 2:
        # always-prompt: 0=Yes, 1=No
        if idx == 0:
            state.permissions.granted = True
            state.permissions.shell_session_granted = False
        else:
            state.permissions.granted = False
            state.permissions.shell_session_granted = False
    else:
        # regular: 0=Yes once, 1=Yes for session, 2=No
        if idx == 0:
            state.permissions.granted = True
            state.permissions.shell_session_granted = False
        elif idx == 1:
            state.permissions.granted = True
            state.permissions.shell_session_granted = True
        else:
            state.permissions.granted = False
            state.permissions.shell_session_granted = False
    state.permissions.awaiting_shell = False
    app._hide_permission_display()
    app._mount_plasma()
    _permission_event.set()


def prompt_sudo_password(app) -> None:
    """Switch to password input mode for sudo."""
    state.ui.mode = "PASSWORD"
    app._set_input_label("[bold yellow] SUDO PASSWORD: [/bold yellow] ")
    app._set_status("Enter sudo password (input masked)")
    inp = app.query_one("#user-input", HistoryInput)
    inp.password = True
    inp.focus()


def handle_password_input(app, password: str) -> None:
    """Handle password submission."""
    state.permissions.sudo_password = password
    state.ui.mode = "CHAT"
    inp = app.query_one("#user-input", HistoryInput)
    inp.password = False
    app._set_input_label("You: ")
    app._set_status("Ready")
    _permission_event.set()


def prompt_api_key(app) -> None:
    """Ask user to enter an API key for the active provider."""
    state.ui.mode = "APIKEY_SET"
    provider = state.provider.active
    app._write(
        "",
        Text(
            f"No API key found for '{provider}'.\n"
            f"Enter your API key (stored in ./config.json):",
            style="yellow",
        ),
    )
    app._set_input_label(f"[bold yellow] {provider.upper()} KEY: [/bold yellow] ")
    app._set_status(f"Enter {provider} API key to continue.")
    app.query_one("#user-input", HistoryInput).focus()


def confirm_personality(app) -> None:
    if not state.reasoning.personality_buffer:
        app._write("", Text("No personality entered — unchanged.", style="dim"))
    else:
        state.reasoning.personality = "\n".join(state.reasoning.personality_buffer)
        save_personality(state.reasoning.personality)
        app._write("", Text("Personality saved.", style="green"))
    state.reasoning.personality_buffer = []
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")


def start_exit_flow(app) -> None:
    """Switch to EXIT_CONFIRM mode and show the reflection prompt."""
    state.ui.mode = "EXIT_CONFIRM"
    app._set_input_label("[bold yellow] REFLECT? [/bold yellow] ")
    app._set_status("Reflect before closing? Consolidates your memories. [Y/n]")
    app._write(
        "",
        Text("Reflect before closing? This will consolidate your memories. [Y/n]", style="yellow"),
    )


def do_exit(app, reflect: bool) -> None:
    """Save session summary and exit. Always exits regardless of errors."""
    if reflect:
        state.ui.mode = "EXITING"
        app._set_input_label("")
        app._set_status("Reflecting and saving summary...")
        app._mount_plasma()
    else:
        state.ui.mode = "CHAT"
        app.exit()
        return

    def _thread():
        from chaosz.session import generate_and_save_session

        try:
            state.trigger_reflection(app)
        except Exception:
            pass
        try:
            generate_and_save_session(app)
        except Exception:
            pass
        try:
            from chaosz.mcp_manager import disconnect_all
            disconnect_all()
        except Exception:
            pass
        app.call_from_thread(app.exit)

    threading.Thread(target=_thread, daemon=True).start()


def _handle_mode_workdir(app, user_input: str) -> bool:
    wd = os.path.realpath(user_input) if user_input else os.path.realpath(os.getcwd())
    if not os.path.isdir(wd):
        app._write("", Text(f"Not a directory: {wd}", style="red"))
        return True
    state.workspace.working_dir = wd
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    app._write("", Text(f"Working directory set: {wd}", style="green"))
    app._mount_plasma()
    _permission_event.set()
    return True


def _handle_mode_apikey(app, user_input: str) -> bool:
    key = user_input.strip()
    if not key:
        app._write("", Text("API key cannot be empty.", style="red"))
        return True
    provider = state.provider.active
    providers, active = load_providers()
    defaults = PROVIDER_REGISTRY.get(provider, PROVIDER_REGISTRY["deepseek"])
    if provider not in providers:
        providers[provider] = {
            "api_key": key,
            "base_url": defaults["base_url"],
            "model": defaults["model"],
            "context_window": defaults["context_window"],
        }
    else:
        providers[provider]["api_key"] = key
    save_providers(providers, active)
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    masked = "..." + key[-4:]
    app._write("", Text(f"Key saved: {masked}", style="green"))
    return True


def _handle_mode_personality_set(app, user_input: str) -> bool:
    if user_input:
        state.reasoning.personality_buffer.append(user_input)
        n = len(state.reasoning.personality_buffer)
        app._set_status(f"Personality: {n} line(s). Empty Enter or Esc to save.")
    else:
        app._confirm_personality()
    return True


def _handle_mode_personality_clear(app, user_input: str) -> bool:
    if user_input.strip().lower() == "yes":
        state.reasoning.personality = ""
        save_personality("")
        app._write("", Text("Personality cleared.", style="green"))
    else:
        app._write("", Text("Clear cancelled.", style="dim"))
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def _handle_mode_model_select(app) -> bool:
    names = state.provider.menu_providers
    if names and state.provider.menu_index < len(names):
        app._confirm_model_switch(names[state.provider.menu_index])
    # confirm_model_switch handles menu cleanup and mode transition
    return True


def _handle_mode_model_add_key(app, user_input: str) -> bool:
    key = user_input.strip()
    if not key:
        app._write("", Text("API key cannot be empty.", style="red"))
        return True
    provider = state.provider.pending
    app._set_status(f"Validating {provider} API key...")
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")

    def _validate_thread():
        ok, err = validate_provider_key(provider, key)
        if ok:
            providers, active = load_providers()
            defaults = PROVIDER_REGISTRY[provider]
            providers[provider] = {
                "api_key": key,
                "base_url": defaults["base_url"],
                "model": defaults["model"],
                "context_window": defaults["context_window"],
            }
            save_providers(providers, active)
            masked = "..." + key[-4:]
            app.call_from_thread(
                app._write,
                "",
                Text(f"Provider '{provider}' added. Key saved ({masked}).", style="green"),
            )
        else:
            app.call_from_thread(app._write, "", Text(f"Validation failed: {err}", style="red"))
        app.call_from_thread(app._set_status, "Ready")

    threading.Thread(target=_validate_thread, daemon=True).start()
    return True


def _handle_mode_model_del_confirm(app, user_input: str) -> bool:
    provider = state.provider.pending
    if user_input.strip().lower() == "yes" and provider:
        providers, active = load_providers()
        model_name = providers.get("ollama", {}).get("model", "") if provider == "ollama" else ""
        providers.pop(provider, None)
        new_active = active if active != provider else next(iter(providers), "deepseek")
        save_providers(providers, new_active)
        if active == provider:
            sync_runtime_provider_state(new_active, providers)
            app._update_footer()
        if provider == "ollama" and model_name:
            app._write("", Text(f"Provider 'ollama' removed from config.", style="green"))
            app._write("", Text(f"Delete model '{model_name}' from disk too? (yes/no)", style="yellow"))
            state.ollama_wizard.del_model = model_name
            state.ui.mode = "OLLAMA_DEL_DISK_CONFIRM"
            app._set_input_label("[bold yellow on red] DELETE FROM DISK? (yes/no) [/bold yellow on red] ")
            return True
        app._write("", Text(f"Provider '{provider}' removed.", style="green"))
    else:
        app._write("", Text("Deletion cancelled.", style="dim"))
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def _handle_mode_ollama_del_disk_confirm(app, user_input: str) -> bool:
    import threading as _threading
    from chaosz.ollama_utils import delete_model
    model_name = state.ollama_wizard.del_model
    r = user_input.strip().lower()
    if r in ("yes", "y"):
        app._write("", Text(f"Deleting {model_name} from disk...", style="dim"))

        def _delete_thread():
            ok, err = delete_model(model_name)
            if ok:
                app.call_from_thread(
                    app._write, "", Text(f"Model '{model_name}' deleted from disk.", style="green")
                )
            else:
                app.call_from_thread(
                    app._write, "", Text(f"Failed to delete model: {err}", style="red")
                )
            state.ollama_wizard.del_model = ""

        _threading.Thread(target=_delete_thread, daemon=True).start()
    else:
        app._write("", Text(f"Model '{model_name}' kept on disk.", style="dim"))
        state.ollama_wizard.del_model = ""
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def _handle_mode_model_add_select(app) -> bool:
    names = state.provider.menu_providers
    if names and state.provider.menu_index < len(names):
        provider = names[state.provider.menu_index]
        app.query("#model-menu").remove()

        if provider == "ollama":
            from chaosz.ui import app_ollama_setup
            app_ollama_setup.start_ollama_setup(app)
            return True

        providers, _ = load_providers()
        if provider in providers:
            app._write("", Text(f"{provider} is already configured. Use /model del {provider} to remove it.", style="yellow"))
            state.ui.mode = "CHAT"
            app._set_input_label("You: ")
            app._set_status("Ready")
            return True

        # Prompt for API key
        state.provider.active = provider
        state.ui.mode = "APIKEY_SET"
        app._set_input_label(f"[bold cyan] {provider.upper()} KEY: [/bold cyan] ")
        app._set_status(f"Enter API key for {provider}")
        return True

    app.query("#model-menu").remove()
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def _handle_mode_model_select_version(app) -> bool:
    from chaosz.ui.app_rendering import KEEP_CURRENT_SENTINEL
    models = state.provider.available_models
    idx = state.provider.available_models_index
    if models and 0 <= idx < len(models):
        selected = models[idx]
        if selected == KEEP_CURRENT_SENTINEL:
            app.query("#model-menu").remove()
            state.ui.mode = "CHAT"
            app._set_input_label("You: ")
            app._set_status("Ready")
            app._write("", Text("Kept current model.", style="dim"))
        else:
            app._render_temp_select_menu(selected)
            state.ui.mode = "TEMP_SELECT"
            app._set_input_label("Temp: ")
            app._set_status("Select temperature, then Enter to confirm")
    else:
        app.query("#model-menu").remove()
        state.ui.mode = "CHAT"
        app._set_input_label("You: ")
        app._set_status("Ready")
    return True


def _handle_mode_temp_select(app) -> bool:
    from chaosz.ui.app_rendering import TEMPERATURE_OPTIONS
    temp_val, temp_label = TEMPERATURE_OPTIONS[state.provider.temp_menu_index]
    app._confirm_model_version_switch(state.provider.pending, temp_val)
    state.provider.pending = ""
    app.query("#model-menu").remove()
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def confirm_skill_add(app) -> None:
    name = state.reasoning.skill_add_name
    if not state.reasoning.skill_add_buffer:
        app._write("", Text("No content entered — skill not saved.", style="dim"))
    else:
        content = "\n".join(state.reasoning.skill_add_buffer)
        from chaosz.skills import save_skill, get_skills_dir
        save_skill(name, content)
        app._write("", Text(f"Skill '{name}' saved. Edit it any time at {get_skills_dir()}/{name}.md", style="green"))
    state.reasoning.skill_add_name = ""
    state.reasoning.skill_add_buffer = []
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")


def _handle_mode_theme_select(app) -> bool:
    names = state.ui.theme_menu_names
    if names and state.ui.theme_menu_index < len(names):
        from chaosz.ui.app_rendering import confirm_theme_switch
        confirm_theme_switch(app, names[state.ui.theme_menu_index])
    return True


def _handle_mode_skill_menu(app) -> bool:
    all_entries = ["none"] + state.ui.skill_menu_names
    idx = state.ui.skill_menu_index
    if 0 <= idx < len(all_entries):
        selected = all_entries[idx]
        if selected == "none":
            state.reasoning.active_skill = None
            save_active_skill(None)
            app._write("", Text("No skill active.", style="dim"))
        else:
            state.reasoning.active_skill = selected
            save_active_skill(selected)
            app._write("", Text(f"Skill '{selected}' activated.", style="green"))
        app._update_footer()
    app.query("#skill-menu").remove()
    state.ui.mode = "CHAT"
    app._set_input_label("You: ")
    app._set_status("Ready")
    return True


def _handle_mode_skill_add(app, user_input: str) -> bool:
    if user_input:
        state.reasoning.skill_add_buffer.append(user_input)
        n = len(state.reasoning.skill_add_buffer)
        app._set_status(f"Skill: {n} line(s). Empty Enter or Esc to save.")
    else:
        app._confirm_skill_add()
    return True


def _handle_mode_dispatch(app, user_input: str) -> bool:
    if state.ui.mode == "WORKDIR_SET":
        return _handle_mode_workdir(app, user_input)
    if state.ui.mode == "APIKEY_SET":
        return _handle_mode_apikey(app, user_input)
    if state.ui.mode == "PERSONALITY_SET":
        return _handle_mode_personality_set(app, user_input)
    if state.ui.mode == "PERSONALITY_CLEAR_CONFIRM":
        return _handle_mode_personality_clear(app, user_input)
    if state.ui.mode == "MODEL_SELECT":
        return _handle_mode_model_select(app)
    if state.ui.mode == "MODEL_SELECT_VERSION":
        return _handle_mode_model_select_version(app)
    if state.ui.mode == "TEMP_SELECT":
        return _handle_mode_temp_select(app)
    if state.ui.mode == "MODEL_ADD_SELECT":
        return _handle_mode_model_add_select(app)
    if state.ui.mode == "MODEL_ADD_KEY":
        return _handle_mode_model_add_key(app, user_input)
    if state.ui.mode == "MODEL_DEL_CONFIRM":
        return _handle_mode_model_del_confirm(app, user_input)
    if state.ui.mode == "OLLAMA_DEL_DISK_CONFIRM":
        return _handle_mode_ollama_del_disk_confirm(app, user_input)
    if state.ui.mode == "PASSWORD":
        app._handle_password_input(user_input)
        return True
    if state.ui.mode == "OLLAMA_SETUP":
        return app._handle_ollama_setup_input(user_input)
    if state.ui.mode == "MCP_SETUP":
        return app._handle_mcp_setup_input(user_input)
    if state.ui.mode == "SKILL_MENU":
        return _handle_mode_skill_menu(app)
    if state.ui.mode == "THEME_SELECT":
        return _handle_mode_theme_select(app)
    if state.ui.mode == "SKILL_ADD":
        return _handle_mode_skill_add(app, user_input)
    if state.ui.mode == "PLAN_APPROVE":
        return _handle_mode_plan_approve(app)
    return False


def _handle_mode_plan_approve(app) -> bool:
    from chaosz.ui.app_rendering import _PLAN_APPROVAL_OPTIONS
    choice = _PLAN_APPROVAL_OPTIONS[state.ui.plan_approval_index]
    state.ui.mode = "CHAT"
    app._hide_plan_approval_display()
    app._confirm_plan_approval(choice)
    return True


def on_input_submitted(app, event: Input.Submitted) -> None:
    user_input = event.value.strip()
    event.input.clear()
    app._history_index = -1
    app._history_draft = ""

    # Permission responses must reach their handlers even while the AI turn is running
    # (the AI thread blocks on _permission_event.wait() while is_thinking is True).
    # These must come before the is_thinking guard.
    if state.permissions.awaiting_shell:
        app._process_shell_permission_response(user_input)
        return

    if state.permissions.awaiting:
        app._process_permission_response(user_input)
        return

    # Block submission while an AI turn is in progress
    if state.ui.is_thinking or state.ui.mode == "EXITING":
        return

    # EXIT_CONFIRM mode — must be before empty-input guard so empty Enter means "yes"
    if state.ui.mode == "EXIT_CONFIRM":
        r = user_input.strip().lower()
        if r in ("n", "no"):
            app._do_exit(reflect=False)
        else:
            app._do_exit(reflect=True)
        return

    # Working directory setup mode — must be checked before the empty-input guard
    # so that pressing Enter with no text accepts the default CWD.
    if _handle_mode_dispatch(app, user_input):
        return

    if not user_input:
        return

    # record every non-empty submission (skip duplicates of the last entry)
    if not app._input_history or app._input_history[-1] != user_input:
        app._input_history.append(user_input)
        save_input_history(app._input_history)

    if user_input.lower() in ("quit", "exit"):
        app._start_exit_flow()
        return

    msg = Static(user_input, classes="user-message")
    app.query_one("#chat-scroll", VerticalScroll).mount(msg)
    app._current_log = None  # next output gets a fresh RichLog
    app.query_one("#chat-scroll", VerticalScroll).scroll_end(animate=False)

    if user_input.startswith("/"):
        handle_command(app, user_input)
        return

    state.session.messages.append({"role": "user", "content": user_input})
    from chaosz.session import append_to_live_session

    append_to_live_session("user", user_input)
    app._run_routed_turn(user_input)
