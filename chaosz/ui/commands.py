import os
import threading

from rich.text import Text

from chaosz.state import state
from chaosz.config import VALID_CATEGORIES, add_memory, save_memory, save_reason_enabled
from chaosz.providers import (
    PROVIDER_REGISTRY,
    load_providers,
    provider_supports_reasoning,
    save_providers,
    sync_runtime_provider_state,
    validate_provider_key,
)
import chaosz.ui.themes as _T



def handle_command(app, user_input: str) -> None:
    args = user_input.split()
    cmd = args[0].lower()

    if cmd == "/help":
        t = _T.get_theme()
        c, a, ac = t.cmd, t.arg, t.accent
        app._write("", Text.from_markup(
            f"\n[bold {ac}]Available Commands:[/bold {ac}]\n"
            f"  [{c}]/help[/{c}]                       - Display this help message\n"
            f"  [{c}]/theme[/{c}]                      - Pick a color theme\n"
            f"  [{c}]/model[/{c}] [{a}]list[/{a}]               - Pick provider, then pick model version + temperature\n"
            f"  [{c}]/model[/{c}] [{a}]add[/{a}]                - Interactive provider addition menu\n"
            f"  [{c}]/model[/{c}] [{a}]del[/{a}] [{a}]<provider>[/{a}]       - Remove a provider\n"
            f"  [{c}]/apikey[/{c}]                     - Update API key for current provider\n"
            f"  [{c}]/personality[/{c}] [{a}]set[/{a}]          - Set communication style: tone, persona, language\n"
            f"  [{c}]/personality[/{c}] [{a}]view[/{a}]         - Show current personality\n"
            f"  [{c}]/personality[/{c}] [{a}]clear[/{a}]        - Remove personality (asks confirmation)\n"
            f"  [{c}]/memory[/{c}] [{a}]show[/{a}]              - Display organized memory categories\n"
            f"  [{c}]/memory[/{c}] [{a}]add[/{a}] [{a}]<c> <t>[/{a}]       - Add text to a memory category\n"
            f"  [{c}]/memory[/{c}] [{a}]forget[/{a}] [{a}]<c> <i>[/{a}]    - Remove specific memory\n"
            f"  [{c}]/memory[/{c}] [{a}]clear[/{a}]             - Wipe all memories\n"
            f"  [{c}]/files[/{c}]                      - Show file operation log for this session\n"
            f"  [{c}]/stats[/{c}]                      - Show token usage for current session\n"
            f"  [{c}]/compact[/{c}]                     - Summarize conversation history and reset token counter\n"
            f"  [{c}]/reason[/{c}] [{a}]on|off[/{a}]             - Toggle reasoning output when supported by the active provider\n"
            f"  [{c}]/header[/{c}]                      - Toggle the ASCII logo header on/off\n"
            f"  [{c}]/skill[/{c}] [{a}]list[/{a}]               - Interactive skill selection menu\n"
            f"  [{c}]/skill[/{c}] [{a}]add[/{a}] [{a}]<name>[/{a}]          - Create a new skill\n"
            f"  [{c}]/skill[/{c}] [{a}]edit[/{a}] [{a}]<name>[/{a}]         - Show file path for external editing\n"
            f"  [{c}]/skill[/{c}] [{a}]remove[/{a}] [{a}]<name>[/{a}]       - Delete a skill\n"
            f"  [{c}]/plan[/{c}] [{a}]on|off[/{a}]               - Toggle plan-before-execute mode (AI plans first, then asks approval)\n"
            f"  [{c}]/mcp[/{c}] [{a}]list|add|remove|enable|disable[/{a}] - Manage MCP servers\n"
            f"  [{c}]quit[/{c}], [{c}]exit[/{c}]                - Exit the application\n"
        ))

    elif cmd == "/apikey":
        app._prompt_api_key()

    elif cmd == "/personality":
        sub = args[1].lower() if len(args) > 1 else "view"
        if sub == "set":
            state.reasoning.personality_buffer = []
            state.ui.mode = "PERSONALITY_SET"
            app._set_input_label("[bold cyan] PERSONALITY: [/bold cyan] ")
            app._set_status("Type personality line by line. Empty Enter or Esc to save.")
            app._write("", Text(
                "Set your communication style: tone, persona, language, verbosity.\n"
                "Examples: 'Be concise', 'You are a snarky senior engineer', 'Respond in Dutch'.\n"
                "This controls HOW the AI talks — not what it does. For task workflows, use /skill.\n"
                "Type line by line. Press Enter on an empty line or Esc to save.",
                style="yellow"
            ))
        elif sub == "view":
            if state.reasoning.personality:
                app._write("", Text(f"Current Personality:\n{state.reasoning.personality}", style="cyan"))
            else:
                app._write("", Text("No personality set.", style="dim"))
        elif sub == "clear":
            if not state.reasoning.personality:
                app._write("", Text("No personality to clear.", style="dim"))
            else:
                state.ui.mode = "PERSONALITY_CLEAR_CONFIRM"
                app._set_input_label("[bold yellow on red] CONFIRM CLEAR? (yes/no): [/bold yellow on red] ")
                app._set_status("Type 'yes' to confirm clearing personality.")

    elif cmd == "/memory":
        sub = args[1].lower() if len(args) > 1 else "show"
        if sub == "show":
            t = _T.get_theme()
            msg = f"\n[bold {t.accent}]Current Memories:[/bold {t.accent}]\n"
            for cat in sorted(VALID_CATEGORIES):
                if state.reasoning.memory[cat]:
                    msg += f"[bold {t.arg}]{cat}[/bold {t.arg}]:\n"
                    for idx, item in enumerate(state.reasoning.memory[cat], 1):
                        msg += f"  {idx}. {item}\n"
            app._write("", Text.from_markup(msg))
        elif sub == "add" and len(args) > 3:
            add_memory(args[2], " ".join(args[3:]))
            app._write("", Text(f"Added memory to {args[2]}.", style="green"))
        elif sub == "forget" and len(args) > 3:
            try:
                cat = args[2]
                idx = int(args[3]) - 1
                removed = state.reasoning.memory[cat].pop(idx)
                save_memory(state.reasoning.memory)
                app._write("", Text(f"Removed memory: '{removed}'", style="green"))
            except Exception:
                app._write("", Text("Invalid category or index.", style="red"))
        elif sub == "clear":
            state.reasoning.memory = {cat: [] for cat in VALID_CATEGORIES}
            save_memory(state.reasoning.memory)
            app._write("", Text("Memory cleared.", style="green"))

    elif cmd == "/files":
        if not state.workspace.file_op_log:
            app._write("", Text("No file operations this session.", style="dim"))
            return
        ac = _T.get_theme().accent
        lines = [f"\n[bold {ac}]File Operations This Session:[/bold {ac}]"]
        for i, entry in enumerate(state.workspace.file_op_log, 1):
            status_color = "green" if entry["status"] == "ok" else (
                "yellow" if entry["status"] == "denied" else "red"
            )
            op = entry["op"]
            if op == "shell_exec":
                op_label = "shell"
                index_suffix = f" [dim]#{entry.get('index', '?')}[/dim]" if "index" in entry else ""
            else:
                op_label = op.replace("file_", "")
                index_suffix = ""
            detail = f"  [dim]{entry['detail']}[/dim]" if entry.get("detail") else ""
            lines.append(
                f"  {i:>3}. [{status_color}]{op_label:<7}[/{status_color}]  "
                f"[white]{entry['path']}[/white]{index_suffix}{detail}"
            )
        if state.workspace.working_dir:
            lines.append(f"\n  [dim]Working dir: {state.workspace.working_dir}[/dim]")
        app._write("", Text.from_markup("\n".join(lines)))

    elif cmd == "/stats":
        msg_chars = sum(len(m.get("content", "")) for m in state.session.messages if m.get("content"))
        estimated = msg_chars // 4
        ctx_ratio = estimated / state.provider.max_ctx if state.provider.max_ctx > 0 else 0
        ctx_max = f"{state.provider.max_ctx // 1000}K" if state.provider.max_ctx >= 1000 else str(state.provider.max_ctx)
        lines = [
            "",
            f"  Prompt tokens:     {state.session.prompt_tokens:,}",
        ]
        if state.session.cached_tokens:
            lines.append(f"  Cached tokens:     {state.session.cached_tokens:,}  (subset of prompt)")
        lines += [
            f"  Completion tokens: {state.session.completion_tokens:,}",
            f"  Total this session:{state.session.tokens:,}",
            "",
            f"  Context window:    ~{estimated:,} / {state.provider.max_ctx:,} tokens  ({ctx_ratio * 100:.1f}% of {ctx_max})",
            "",
        ]
        ac = _T.get_theme().accent
        app._write("", Text.from_markup(
            f"\n[bold {ac}]Token Usage[/bold {ac}]\n" + "\n".join(lines)
        ))

    elif cmd == "/compact":
        if state.ui.is_thinking:
            app._write("", Text("Cannot compact while AI is thinking.", style="yellow"))
            return
        if state.background.compacting:
            app._write("", Text("Compaction already in progress.", style="yellow"))
            return
        # Run compaction in background thread to avoid blocking UI
        def compact_thread():
            state.ui.is_thinking = True
            try:
                app._compact_conversation(auto=False)
            finally:
                state.ui.is_thinking = False
        threading.Thread(target=compact_thread, daemon=True).start()

    elif cmd == "/reason":
        sub = args[1].lower() if len(args) > 1 else "status"
        provider = state.provider.active
        supported = provider_supports_reasoning(provider)
        if sub == "on":
            if not supported:
                app._write("", Text(f"Reasoning mode is not supported for '{provider}'.", style="yellow"))
                return
            state.reasoning.enabled = True
            save_reason_enabled(True)
            sync_runtime_provider_state(provider)
            app._write("", Text(f"Reasoning ON ({state.provider.model}). Responses will include model thinking.", style="green"))
            app._update_footer()
        elif sub == "off":
            if not supported:
                app._write("", Text(f"Reasoning mode is not supported for '{provider}'.", style="yellow"))
                return
            state.reasoning.enabled = False
            save_reason_enabled(False)
            sync_runtime_provider_state(provider)
            app._write("", Text(f"Reasoning OFF ({state.provider.model}).", style="dim"))
            app._update_footer()
        else:
            status = "ON" if state.reasoning.enabled else "OFF"
            if supported:
                msg = f"Reasoning is currently {status} for '{provider}'. Use /reason on or /reason off."
            else:
                msg = f"Reasoning is currently {status}, but '{provider}' does not use it."
            app._write("", Text(msg, style="cyan"))

    elif cmd == "/model":
        sub = args[1].lower() if len(args) > 1 else "list"

        if sub == "list":
            providers, _ = load_providers()
            if not providers:
                app._write("", Text("No providers configured. Use /model add.", style="yellow"))
                return
            state.provider.menu_index = 0
            state.ui.mode = "MODEL_SELECT"
            app._set_input_label("[bold cyan] MODEL: [/bold cyan] ")
            app._set_status("↑/↓ navigate   Enter confirm   Esc cancel")
            app._render_model_menu()

        elif sub == "add":
            state.provider.menu_index = 0
            state.ui.mode = "MODEL_ADD_SELECT"
            app._set_input_label("[bold cyan] ADD PROVIDER: [/bold cyan] ")
            app._set_status("↑/↓ navigate   Enter confirm   Esc cancel")
            app._render_model_menu()

        elif sub == "del":
            if len(args) < 3:
                app._write("", Text("Usage: /model del <provider>", style="yellow"))
                return
            provider = args[2].lower()
            providers, _ = load_providers()
            if provider not in providers:
                app._write("", Text(f"Provider '{provider}' is not configured.", style="red"))
                return
            if len(providers) == 1:
                app._write("", Text("Cannot remove the only configured provider.", style="red"))
                return
            state.provider.pending = provider
            state.ui.mode = "MODEL_DEL_CONFIRM"
            app._set_input_label("[bold yellow on red] CONFIRM DEL? (yes/no): [/bold yellow on red] ")
            app._set_status(f"Type 'yes' to confirm removing {provider}.")
            app._write("", Text(
                f"Remove provider '{provider}'? This will delete its stored API key.\nType yes to confirm:",
                style="yellow"
            ))

        else:
            app._write("", Text(
                "Usage: /model list | /model add | /model del <provider>",
                style="yellow"
            ))

    elif cmd == "/mcp":
        sub = args[1].lower() if len(args) > 1 else "list"

        if sub == "list":
            from chaosz.config import load_mcp_servers
            from chaosz.mcp_manager import get_connection_status
            servers = load_mcp_servers()
            if not servers:
                app._write("", Text("No MCP servers configured. Use /mcp add to add one.", style="dim"))
                return
            statuses = {s["name"]: s for s in get_connection_status()}
            lines = ["\n[bold cyan]MCP Servers:[/bold cyan]"]
            for sname, scfg in servers.items():
                st = statuses.get(sname, {})
                if not scfg.get("enabled", True):
                    color, badge = "dim", "DISABLED"
                elif st.get("connected"):
                    color, badge = "green", f"CONNECTED ({st['tool_count']} tools)"
                else:
                    err = st.get("error") or "not connected"
                    color, badge = "yellow", f"DISCONNECTED ({str(err)[:50]})"
                transport = scfg.get("transport", "?")
                desc = scfg.get("description", "")
                desc_str = f"  [dim]{desc}[/dim]" if desc else ""
                lines.append(
                    f"  [{color}]●[/{color}]  [white]{sname}[/white] "
                    f"[dim]({transport})[/dim] [{color}]{badge}[/{color}]{desc_str}"
                )
            app._write("", Text.from_markup("\n".join(lines)))

        elif sub == "add":
            from chaosz.ui import app_mcp_setup
            app_mcp_setup.start_mcp_add_wizard(app)

        elif sub == "remove" and len(args) > 2:
            name = args[2]
            from chaosz.config import load_mcp_servers, save_mcp_servers
            from chaosz.mcp_manager import disconnect_server
            servers = load_mcp_servers()
            if name not in servers:
                app._write("", Text(f"No MCP server named '{name}'.", style="red"))
                return
            servers.pop(name)
            save_mcp_servers(servers)
            disconnect_server(name)
            app._write("", Text(f"MCP server '{name}' removed.", style="green"))

        elif sub == "enable" and len(args) > 2:
            name = args[2]
            from chaosz.config import load_mcp_servers, save_mcp_servers
            servers = load_mcp_servers()
            if name not in servers:
                app._write("", Text(f"No MCP server named '{name}'.", style="red"))
                return
            servers[name]["enabled"] = True
            save_mcp_servers(servers)
            app._write("", Text(f"Enabling '{name}'...", style="cyan"))

            def _do_enable(server_name=name, cfg=servers[name]):
                from chaosz.mcp_manager import connect_server
                conn = connect_server(server_name, cfg)
                if conn.connected:
                    app.call_from_thread(
                        app._write, "",
                        Text(f"Connected to '{server_name}'. {len(conn.tools)} tool(s) available.", style="green"),
                    )
                else:
                    app.call_from_thread(
                        app._write, "",
                        Text(f"Failed to connect '{server_name}': {conn.error}", style="yellow"),
                    )
            threading.Thread(target=_do_enable, daemon=True).start()

        elif sub == "disable" and len(args) > 2:
            name = args[2]
            from chaosz.config import load_mcp_servers, save_mcp_servers
            from chaosz.mcp_manager import disconnect_server
            servers = load_mcp_servers()
            if name not in servers:
                app._write("", Text(f"No MCP server named '{name}'.", style="red"))
                return
            servers[name]["enabled"] = False
            save_mcp_servers(servers)
            disconnect_server(name)
            app._write("", Text(f"MCP server '{name}' disabled.", style="dim"))

        else:
            t = _T.get_theme()
            c, a, ac = t.cmd, t.arg, t.accent
            app._write("", Text.from_markup(
                f"\n[bold {ac}]MCP Commands:[/bold {ac}]\n"
                f"  [{c}]/mcp[/{c}] [{a}]list[/{a}]                   - Show all MCP servers and status\n"
                f"  [{c}]/mcp[/{c}] [{a}]add[/{a}]                    - Interactive wizard to add a server\n"
                f"  [{c}]/mcp[/{c}] [{a}]remove[/{a}] [{a}]<name>[/{a}]         - Remove a server\n"
                f"  [{c}]/mcp[/{c}] [{a}]enable[/{a}] [{a}]<name>[/{a}]         - Enable and connect a server\n"
                f"  [{c}]/mcp[/{c}] [{a}]disable[/{a}] [{a}]<name>[/{a}]        - Disable and disconnect a server\n"
            ))

    elif cmd == "/skill":
        sub = args[1].lower() if len(args) > 1 else ""

        if sub == "list" or sub == "":
            state.ui.skill_menu_index = 0
            state.ui.mode = "SKILL_MENU"
            app._set_input_label("[bold cyan] SKILL: [/bold cyan] ")
            app._set_status("↑/↓ navigate   Enter confirm   Esc cancel")
            app._render_skill_menu()

        elif sub == "add":
            if len(args) < 3:
                app._write("", Text("Usage: /skill add <name>", style="yellow"))
                return
            raw_name = args[2]
            # Sanitize: lowercase, alphanumeric + hyphens only, no path separators
            import re as _re
            name = _re.sub(r"[^a-z0-9\-]", "-", raw_name.lower()).strip("-")
            if not name:
                app._write("", Text("Invalid skill name. Use letters, numbers, and hyphens only.", style="red"))
                return
            from chaosz.skills import get_skills_dir
            state.reasoning.skill_add_name = name
            state.reasoning.skill_add_buffer = []
            state.ui.mode = "SKILL_ADD"
            app._set_input_label(f"[bold cyan] SKILL ({name}): [/bold cyan] ")
            app._set_status("Type skill content line by line. Empty Enter or Esc to save.")
            app._write("", Text(
                f"Define task mode for '{name}': workflow rules, methodology, conventions.\n"
                f"Examples: 'Always read files before editing', 'Summarize what changed after each edit'.\n"
                f"This controls WHAT the AI does and how it approaches tasks — not its tone.\n"
                f"For tone/persona, use /personality set instead.\n"
                f"Type line by line. Press Enter on an empty line or Esc to save.\n"
                f"File will be saved to: {get_skills_dir()}/{name}.md",
                style="yellow"
            ))

        elif sub == "remove":
            if len(args) < 3:
                app._write("", Text("Usage: /skill remove <name>", style="yellow"))
                return
            name = args[2]
            from chaosz.skills import delete_skill
            if delete_skill(name):
                if state.reasoning.active_skill == name:
                    state.reasoning.active_skill = None
                    from chaosz.config import save_active_skill
                    save_active_skill(None)
                    app._update_footer()
                app._write("", Text(f"Skill '{name}' removed.", style="green"))
            else:
                app._write("", Text(f"Skill '{name}' not found.", style="red"))

        elif sub == "edit":
            if len(args) < 3:
                app._write("", Text("Usage: /skill edit <name>", style="yellow"))
                return
            name = args[2]
            from chaosz.skills import list_skills, get_skills_dir
            if name not in list_skills():
                app._write("", Text(f"Skill '{name}' not found. Use /skill list to see available skills.", style="red"))
                return
            path = f"{get_skills_dir()}/{name}.md"
            app._write("", Text.from_markup(
                f"Edit [cyan]{name}[/cyan] directly in your text editor:\n"
                f"  [dim]{path}[/dim]\n"
                f"Changes take effect on the next message (no restart needed)."
            ))

        else:
            t = _T.get_theme()
            c, a, ac = t.cmd, t.arg, t.accent
            app._write("", Text.from_markup(
                f"\n[bold {ac}]Skill Commands:[/bold {ac}]\n"
                f"  [{c}]/skill[/{c}] [{a}]list[/{a}]               - Interactive skill selection menu\n"
                f"  [{c}]/skill[/{c}] [{a}]add[/{a}] [{a}]<name>[/{a}]          - Create a new skill (multiline input)\n"
                f"  [{c}]/skill[/{c}] [{a}]edit[/{a}] [{a}]<name>[/{a}]         - Show file path for external editing\n"
                f"  [{c}]/skill[/{c}] [{a}]remove[/{a}] [{a}]<name>[/{a}]       - Delete a skill\n"
            ))

    elif cmd == "/theme":
        from chaosz.ui.themes import list_themes
        names = list_themes()
        if not names:
            app._write("", Text("No themes found.", style="yellow"))
            return
        state.ui.theme_menu_names = names
        state.ui.theme_menu_index = 0
        state.ui.mode = "THEME_SELECT"
        app._render_theme_menu()

    elif cmd == "/header":
        from chaosz.config import save_show_header
        header = app.query_one("#header")
        visible = not header.display
        header.display = visible
        save_show_header(visible)
        app._write("", Text(
            "Header shown." if visible else "Header hidden. Type /header to bring it back.",
            style="dim"
        ))

    elif cmd == "/plan":
        sub = args[1].lower() if len(args) > 1 else None
        if sub == "on" or (sub is None and not state.ui.plan_mode):
            state.ui.plan_mode = True
            app._update_footer()
            app._write("", Text.from_markup(
                "[bold magenta]Plan mode ON.[/bold magenta] The AI will present a numbered plan "
                "and ask for your approval before executing any tools."
            ))
        elif sub == "off" or (sub is None and state.ui.plan_mode):
            state.ui.plan_mode = False
            app._update_footer()
            app._write("", Text("[dim]Plan mode off.[/dim]"))
        else:
            app._write("", Text.from_markup(
                "[bold cyan]Usage:[/bold cyan] [purple]/plan[/purple] [green]on|off[/green]  "
                "— toggle plan-before-execute mode\n"
                "Currently: " + ("[bold magenta]ON[/bold magenta]" if state.ui.plan_mode else "[dim]off[/dim]")
            ))

    elif cmd in ("/exit", "/quit"):
        app._start_exit_flow()

    else:
        app._write("", Text(f"Unknown command: {cmd}. Type /help for available commands.", style="red"))
