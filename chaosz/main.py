import os
from datetime import datetime

from chaosz.state import state
from chaosz.config import load_config, load_memory, load_personality, load_reason_enabled, load_input_history, load_active_skill, load_theme
from chaosz.providers import load_providers, PROVIDER_REGISTRY
from chaosz.config import CHAOSZ_DIR
from chaosz.shell import _setup_session_logs
from chaosz.session import startup_cleanup, restore_session
from chaosz.ui.themes import seed_builtin_themes, set_theme
from chaosz.ui.app import ChaoszApp


def _reset_tool_result_log() -> None:
    logs_dir = os.path.join(CHAOSZ_DIR, "logs")
    log_path = os.path.join(logs_dir, "tool_result.log")
    try:
        os.makedirs(logs_dir, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("=== Chaosz CLI Tool Result Log ===\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Path: {log_path}\n")
            f.write("==================================\n\n")
    except OSError:
        pass


def _reset_ai_turn_log() -> None:
    logs_dir = os.path.join(CHAOSZ_DIR, "logs")
    log_path = os.path.join(logs_dir, "ai_turn.log")
    try:
        os.makedirs(logs_dir, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("=== Chaosz CLI AI Turn Log ===\n")
            f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Path: {log_path}\n")
            f.write("==============================\n\n")
    except OSError:
        pass


def main():
    state.session.log_path = _setup_session_logs()
    _reset_tool_result_log()
    _reset_ai_turn_log()
    state.provider.config = load_config()
    state.reasoning.memory = load_memory()
    state.reasoning.personality = load_personality()
    state.reasoning.enabled = load_reason_enabled()
    from chaosz.skills import ensure_skills_dir
    ensure_skills_dir()
    seed_builtin_themes()
    set_theme(load_theme())
    state.reasoning.active_skill = load_active_skill()

    # Automatically target the current directory where the user launched the command.
    # Since we removed working_dir from the global config.json, this will correctly
    # reset to the actual CWD every time you start the app in a new project.
    state.workspace.working_dir = os.getcwd()

    providers, active = load_providers()
    state.provider.active = active
    pdata = providers.get(active) or {}
    fallback = PROVIDER_REGISTRY.get(active, PROVIDER_REGISTRY["deepseek"])
    state.provider.model = pdata.get("model") or fallback.get("model") or "?"
    state.provider.max_ctx = pdata.get("context_window", fallback["context_window"])
    state.provider.max_output_tokens = pdata.get("max_output_tokens", fallback.get("max_output_tokens", 8192))
    state.provider.temperature = pdata.get("temperature", 0.7)

    startup_cleanup()
    restore_session()

    # Connect enabled MCP servers in the background so startup isn't delayed.
    # Tools become available once connections complete (~1-3 s for typical servers).
    def _init_mcp() -> None:
        from chaosz.config import load_mcp_servers
        from chaosz.mcp_manager import connect_server
        for srv_name, srv_cfg in load_mcp_servers().items():
            if srv_cfg.get("enabled", True):
                try:
                    connect_server(srv_name, srv_cfg)
                except Exception:
                    pass  # failures are visible via /mcp list

    import threading as _threading
    _threading.Thread(target=_init_mcp, daemon=True, name="mcp-startup").start()

    app = ChaoszApp()
    app._input_history = load_input_history()
    app.run()


if __name__ == "__main__":
    main()
