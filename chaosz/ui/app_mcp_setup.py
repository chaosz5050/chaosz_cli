"""MCP server setup wizard.

Follows the same background-thread pattern as app_ollama_setup.py:
a daemon thread drives the wizard, blocking on threading.Event until
the user submits each answer via handle_mcp_setup_input().
"""

import re
import threading

from rich.text import Text

from chaosz.config import load_mcp_servers, save_mcp_servers
from chaosz.state import state


def start_mcp_add_wizard(app) -> None:
    """Launch the interactive MCP add wizard in a background thread."""
    event = threading.Event()
    state.mcp_wizard.input_event = event

    def _wizard() -> None:

        def _write(msg: str, style: str = "yellow") -> None:
            app.call_from_thread(app._write, "", Text(msg, style=style))

        def _prompt(step: str, message: str, label: str, status: str) -> None:
            """Display message, switch to MCP_SETUP mode, block until user submits."""
            event.clear()
            state.mcp_wizard.step = step

            def _ui() -> None:
                app._write("", Text(message, style="yellow"))
                app._set_input_label(label)
                app._set_status(status)
                state.ui.mode = "MCP_SETUP"

            app.call_from_thread(_ui)
            event.wait()

        def _reset() -> None:
            def _ui() -> None:
                state.ui.mode = "CHAT"
                state.mcp_wizard.step = ""
                app._set_input_label("You: ")
                app._set_status("Ready")

            app.call_from_thread(_ui)

        def _cancelled() -> bool:
            """Return True if user pressed Escape (empty sentinel answer)."""
            return state.mcp_wizard.input_answer == "\x00CANCEL\x00"

        # ---- STEP 1: server name ----------------------------------------

        while True:
            _prompt(
                "NAME",
                "Enter a name for this MCP server (letters, numbers, hyphens/underscores):",
                "[bold cyan] MCP NAME: [/bold cyan] ",
                "Enter a short identifier for the server",
            )
            if _cancelled():
                _write("MCP setup cancelled.", "dim")
                _reset()
                return
            name = state.mcp_wizard.input_answer.strip()
            if not name:
                _write("Name cannot be empty.", "red")
                continue
            if not re.match(r"^[a-zA-Z0-9_-]+$", name):
                _write("Invalid name — use letters, numbers, hyphens, or underscores only.", "red")
                continue
            existing = load_mcp_servers()
            if name in existing:
                _write(f"A server named '{name}' already exists. Use /mcp remove {name} first.", "red")
                continue
            break

        # ---- STEP 2: transport ------------------------------------------

        while True:
            _prompt(
                "TRANSPORT",
                "Transport type?\n  stdio  — local subprocess (e.g. npx, python)\n  sse    — remote HTTP server",
                "[bold cyan] MCP TRANSPORT: [/bold cyan] ",
                "Enter 'stdio' or 'sse'",
            )
            if _cancelled():
                _write("MCP setup cancelled.", "dim")
                _reset()
                return
            transport = state.mcp_wizard.input_answer.strip().lower()
            if transport in ("stdio", "sse"):
                break
            _write("Please enter 'stdio' or 'sse'.", "red")

        # ---- STEP 3a/3b: command or URL ---------------------------------

        if transport == "stdio":
            while True:
                _prompt(
                    "COMMAND",
                    "Enter the full command to launch the MCP server.\n"
                    "Examples:\n"
                    "  npx -y @modelcontextprotocol/server-filesystem /home/user\n"
                    "  python /path/to/my_mcp_server.py",
                    "[bold cyan] MCP COMMAND: [/bold cyan] ",
                    "Enter the stdio launch command",
                )
                if _cancelled():
                    _write("MCP setup cancelled.", "dim")
                    _reset()
                    return
                command = state.mcp_wizard.input_answer.strip()
                if command:
                    break
                _write("Command cannot be empty.", "red")
            url = None
        else:
            while True:
                _prompt(
                    "URL",
                    "Enter the SSE server URL.\n"
                    "Example: http://localhost:8080/sse",
                    "[bold cyan] MCP URL: [/bold cyan] ",
                    "Enter the remote SSE URL",
                )
                if _cancelled():
                    _write("MCP setup cancelled.", "dim")
                    _reset()
                    return
                url = state.mcp_wizard.input_answer.strip()
                if url.startswith("http://") or url.startswith("https://"):
                    break
                _write("URL must start with http:// or https://", "red")
            command = None

        # ---- STEP 4: description (optional) -----------------------------

        _prompt(
            "DESCRIPTION",
            "Optional description (press Enter to skip):",
            "[bold cyan] MCP DESC: [/bold cyan] ",
            "Enter a short description (optional)",
        )
        if _cancelled():
            _write("MCP setup cancelled.", "dim")
            _reset()
            return
        description = state.mcp_wizard.input_answer.strip()

        # ---- STEP 5: confirm + connect ----------------------------------

        preview = command or url or ""
        _prompt(
            "CONFIRM",
            f"Add MCP server '{name}' ({transport}: {preview[:60]}) and connect now? (yes/no)",
            "[bold yellow] CONFIRM? (yes/no): [/bold yellow] ",
            f"Confirm adding '{name}'",
        )
        if _cancelled() or state.mcp_wizard.input_answer.strip().lower() != "yes":
            _write("MCP server addition cancelled.", "dim")
            _reset()
            return

        # Save to config
        cfg = {
            "transport": transport,
            "command": command,
            "url": url,
            "enabled": True,
            "description": description,
        }
        servers = load_mcp_servers()
        servers[name] = cfg
        save_mcp_servers(servers)
        _write(f"Saved '{name}'. Connecting...", "cyan")

        # Attempt connection
        from chaosz.mcp_manager import connect_server
        try:
            conn = connect_server(name, cfg)
            if conn.connected:
                tool_names = [t["function"]["name"].split("__", 1)[1] for t in conn.tools[:5]]
                suffix = "..." if len(conn.tools) > 5 else ""
                _write(
                    f"Connected to '{name}'. {len(conn.tools)} tool(s): "
                    + ", ".join(tool_names) + suffix,
                    "green",
                )
            else:
                _write(f"Saved but failed to connect: {conn.error}", "yellow")
                _write("Server is saved and will be retried on next startup.", "dim")
        except Exception as exc:
            _write(f"Saved but connection error: {exc}", "yellow")

        _reset()

    threading.Thread(target=_wizard, daemon=True, name="mcp-wizard").start()


def handle_mcp_setup_input(app, user_input: str) -> bool:
    """Handle user input while in MCP_SETUP mode.

    Called from the mode dispatch in app_input_modes.py.
    Passes the answer to the waiting wizard thread via _mcp_input_event.
    Returns True to signal the input was consumed.
    """
    state.mcp_wizard.input_answer = user_input.strip()
    if state.mcp_wizard.input_event is not None:
        state.mcp_wizard.input_event.set()
    return True


def cancel_mcp_setup(app) -> None:
    """Cancel the wizard (called on Escape key in MCP_SETUP mode)."""
    state.mcp_wizard.input_answer = "\x00CANCEL\x00"
    if state.mcp_wizard.input_event is not None:
        state.mcp_wizard.input_event.set()
