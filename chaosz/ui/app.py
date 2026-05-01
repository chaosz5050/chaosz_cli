from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Key
from textual.widgets import RichLog, Static

from chaosz import __version__
from chaosz.providers import load_providers
from chaosz.state import state
from chaosz.ui import app_ai_turn, app_compaction, app_compose_turn, app_input_modes, app_investigation_turn, app_mcp_setup, app_ollama_setup, app_rendering, app_runtime, routing
from chaosz.ui.plasma import ReflectingAnimation
from chaosz.ui.themes import get_theme
from chaosz.ui.widgets import HistoryInput


def _build_css(t) -> str:
    return f"""
    Screen {{
        background: {t.bg_main};
    }}

    #header {{
        dock: top;
        height: 11;
        color: {t.header_text};
        background: {t.bg_main};
        padding: 0 1;
        border-bottom: solid {t.border};
    }}

    #chat-scroll {{
        background: {t.bg_main};
        color: {t.text};
        scrollbar-background: {t.bg_input};
        scrollbar-color: {t.scrollbar};
        scrollbar-corner-color: {t.bg_main};
    }}

    .user-message {{
        background: {t.user_msg_bg};
        width: 100%;
        padding: 0 0 0 4;
        margin-top: 1;
    }}

    .ai-log {{
        background: {t.bg_main};
        color: {t.text};
        height: auto;
    }}

    /* Single dock:bottom container holds all three bottom elements.
       Children stack top-to-bottom in compose() order — no ambiguity. */

    #bottom-panel {{
        dock: bottom;
        height: 7;
        background: {t.bg_main};
    }}

    #status-bar {{
        height: 1;
        background: {t.bg_statusbar};
        color: {t.text_dim};
        padding: 0 1;
    }}

    #input-row {{
        height: 5;
        background: {t.border};
    }}

    #plasma-animation {{
        display: none;
        width: 1fr;
        height: 5;
    }}

    #plan-approval-display {{
        display: none;
        width: 1fr;
        height: 5;
    }}

    #permission-display {{
        display: none;
        width: 1fr;
        height: 5;
    }}

    #input-label {{
        width: auto;
        height: 5;
        content-align: left middle;
        padding: 2 0 2 1;
        color: {t.input_label};
        text-style: bold;
    }}

    #user-input {{
        width: 1fr;
        background: transparent;
        color: {t.text};
        border: none;
        height: 5;
        padding: 2 1;
    }}

    #user-input:focus {{
        border: none;
        background: transparent;
    }}

    #info-bar-container {{
        height: 1;
        background: {t.bg_infobar};
    }}

    #info-bar {{
        width: 1fr;
        color: {t.text_info};
        padding: 0 1;
        background: transparent;
    }}

    #version-bar {{
        width: auto;
        content-align: right middle;
        color: {t.text_version};
        padding: 0 1;
        background: transparent;
    }}
    """

ASCII_LOGO = r"""
  ██████╗██╗  ██╗ █████╗  ██████╗ ███████╗███████╗
 ██╔════╝██║  ██║██╔══██╗██╔═══██╗██╔════╝╚══███╔╝
 ██║     ███████║███████║██║   ██║███████╗  ███╔╝
 ██║     ██╔══██║██╔══██║██║   ██║╚════██║ ███╔╝
 ╚██████╗██║  ██║██║  ██║╚██████╔╝███████║███████╗
  ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚══════╝
        C L I  —  Plug in a brain. Own the chaos."""


class ChaoszApp(App):
    CSS = _build_css(get_theme())

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    # session-level input history (up/down to cycle, persisted to disk)
    _input_history: list[str]
    _history_index: int = -1   # -1 = not navigating
    _history_draft: str = ""   # preserves what was typed before navigating

    # glitch animation state
    _glitch_timer = None
    _glitch_frame_idx: int = 0

    # reflect glitch animation state
    _reflect_timer = None
    _reflect_frame_idx: int = 0
    _plasma_widget: object | None = None

    # active RichLog for AI/system output; None forces creation of a new one
    _current_log: RichLog | None = None

    # Method-binding pattern:
    # We bind module-level functions to the class to keep the main ChaoszApp
    # clean while allowing the UI logic to be split across specialized modules.
    # These functions are called as app._method(...) and receive 'app' as the 
    # first argument (like 'self' for instance methods).

    # Rendering / model menu
    _get_or_create_log = app_rendering.get_or_create_log
    _write = app_rendering.write
    _set_status = app_rendering.set_status
    _set_input_label = app_rendering.set_input_label
    _update_footer = app_rendering.update_footer
    _write_ai_turn = app_rendering.write_ai_turn
    _render_ai_text = app_rendering.render_ai_text
    _start_reasoning_block = app_rendering.start_reasoning_block
    _append_reasoning_line = app_rendering.append_reasoning_line
    _end_reasoning_block = app_rendering.end_reasoning_block
    _write_reasoning_block = app_rendering.write_reasoning_block
    _render_model_menu = app_rendering.render_model_menu
    _navigate_model_menu = app_rendering.navigate_model_menu
    _confirm_model_switch = app_rendering.confirm_model_switch
    _render_model_version_menu = app_rendering.render_model_version_menu
    _navigate_model_version_menu = app_rendering.navigate_model_version_menu
    _confirm_model_version_switch = app_rendering.confirm_model_version_switch
    _render_temp_select_menu = app_rendering.render_temp_select_menu
    _navigate_temp_menu = app_rendering.navigate_temp_menu
    _render_skill_menu = app_rendering.render_skill_menu
    _navigate_skill_menu = app_rendering.navigate_skill_menu
    _render_theme_menu = app_rendering.render_theme_menu
    _navigate_theme_menu = app_rendering.navigate_theme_menu
    _render_plan_approval_menu = app_rendering.render_plan_approval_menu
    _navigate_plan_approval_menu = app_rendering.navigate_plan_approval_menu
    _confirm_plan_approval = app_rendering.confirm_plan_approval
    _hide_plan_approval_display = app_rendering.hide_plan_approval_display
    _show_permission_display = app_rendering.show_permission_display
    _hide_permission_display = app_rendering.hide_permission_display
    _navigate_permission_menu = app_rendering.navigate_permission_menu

    # Runtime / animation / reflection-idle
    _start_glitch = app_runtime.start_glitch
    _tick_glitch = app_runtime.tick_glitch
    _stop_glitch = app_runtime.stop_glitch
    _mount_plasma = app_runtime.mount_plasma
    _unmount_plasma = app_runtime.unmount_plasma
    _start_reflect_glitch = app_runtime.start_reflect_glitch
    _tick_reflect_glitch = app_runtime.tick_reflect_glitch
    _stop_reflect_glitch = app_runtime.stop_reflect_glitch

    # Input modes / prompts / confirmation / exit
    _show_tool_permission_prompt = app_input_modes.show_tool_permission_prompt
    _prompt_working_dir = app_input_modes.prompt_working_dir
    _process_permission_response = app_input_modes.process_permission_response
    _show_shell_permission_prompt = app_input_modes.show_shell_permission_prompt
    _process_shell_permission_response = app_input_modes.process_shell_permission_response
    _prompt_sudo_password = app_input_modes.prompt_sudo_password
    _handle_password_input = app_input_modes.handle_password_input
    _prompt_api_key = app_input_modes.prompt_api_key
    _confirm_personality = app_input_modes.confirm_personality
    _confirm_skill_add = app_input_modes.confirm_skill_add
    _start_exit_flow = app_input_modes.start_exit_flow
    _do_exit = app_input_modes.do_exit
    _start_ollama_setup = app_ollama_setup.start_ollama_setup
    _handle_ollama_setup_input = app_ollama_setup.handle_ollama_setup_input
    _start_mcp_add_wizard = app_mcp_setup.start_mcp_add_wizard
    _handle_mcp_setup_input = app_mcp_setup.handle_mcp_setup_input
    _cancel_mcp_setup = app_mcp_setup.cancel_mcp_setup

    # Compaction / summary
    _estimate_tokens = app_compaction.estimate_tokens
    _filter_messages_for_summary = app_compaction.filter_messages_for_summary
    _generate_summary = app_compaction.generate_summary
    _compact_conversation = app_compaction.compact_conversation
    _check_and_compact_if_needed = app_compaction.check_and_compact_if_needed

    # AI turn loop
    _run_ai_turn = app_ai_turn.run_ai_turn
    _run_compose_turn = app_compose_turn.run_compose_turn
    _run_investigation_turn = app_investigation_turn.run_investigation_turn
    _run_routed_turn = routing.run_routed_turn

    # Submitted-input dispatcher
    on_input_submitted = app_input_modes.on_input_submitted

    def compose(self) -> ComposeResult:
        _tc = get_theme().title_color or get_theme().header_text
        yield Static(ASCII_LOGO + f"\n\n [{_tc}]Welcome to Chaosz CLI. /help for commands.[/]", id="header")
        yield VerticalScroll(id="chat-scroll")
        with Vertical(id="bottom-panel"):
            yield Static("▶ Ready", id="status-bar")
            yield Horizontal(
                ReflectingAnimation(id="plasma-animation"),
                Static("", id="plan-approval-display"),
                Static("", id="permission-display"),
                Static("You: ", id="input-label"),
                HistoryInput(placeholder="", id="user-input"),
                id="input-row",
            )
            with Horizontal(id="info-bar-container"):
                yield Static("", id="info-bar")
                yield Static(f"v{__version__}", id="version-bar")

    def on_mount(self) -> None:
        from chaosz.config import load_show_header
        self.query_one("#header").display = load_show_header()
        self._update_footer()
        self.query_one("#user-input", HistoryInput).focus()
        providers, active = load_providers()
        if not providers.get(active, {}).get("api_key"):
            self._prompt_api_key()
        if active == "ollama":
            model = providers.get("ollama", {}).get("model", "")
            if model:
                from chaosz.ollama_utils import get_model_context_window
                from chaosz.providers import save_providers
                ctx = get_model_context_window(model)
                if ctx != providers["ollama"].get("context_window", 8192):
                    providers["ollama"]["context_window"] = ctx
                    save_providers(providers, active)
                state.provider.max_ctx = ctx
                self._update_footer()

    def apply_theme(self, name: str) -> bool:
        from chaosz.ui.themes import set_theme, get_theme as _get_theme
        if not set_theme(name):
            return False
        t = _get_theme()
        # Keep CSS in sync for widgets created after this point
        ChaoszApp.CSS = _build_css(t)

        # refresh_css() doesn't update existing widgets — set inline styles directly
        def _s(widget, **props):
            for k, v in props.items():
                try:
                    setattr(widget.styles, k, v)
                except Exception:
                    pass

        try: _s(self.screen, background=t.bg_main)
        except Exception: pass

        try:
            h = self.query_one("#header")
            _s(h, background=t.bg_main, color=t.header_text)
            h.styles.border_bottom = ("solid", t.border)
            title_color = t.title_color or t.header_text
            h.update(ASCII_LOGO + f"\n\n [{title_color}]Welcome to Chaosz CLI. /help for commands.[/]")
        except Exception: pass

        try:
            cs = self.query_one("#chat-scroll")
            _s(cs, background=t.bg_main, color=t.text,
               scrollbar_background=t.bg_input, scrollbar_color=t.scrollbar,
               scrollbar_corner_color=t.bg_main)
        except Exception: pass

        try: _s(self.query_one("#bottom-panel"), background=t.bg_main)
        except Exception: pass
        try: _s(self.query_one("#status-bar"), background=t.bg_statusbar, color=t.text_dim)
        except Exception: pass
        try: _s(self.query_one("#input-row"), background=t.border)
        except Exception: pass
        try: _s(self.query_one("#input-label"), color=t.input_label)
        except Exception: pass
        try: _s(self.query_one("#user-input"), color=t.text)
        except Exception: pass
        try: _s(self.query_one("#info-bar-container"), background=t.bg_infobar)
        except Exception: pass
        try: _s(self.query_one("#info-bar"), color=t.text_info)
        except Exception: pass
        try: _s(self.query_one("#version-bar"), color=t.text_version)
        except Exception: pass

        for msg in self.query(".user-message"):
            try: _s(msg, background=t.user_msg_bg)
            except Exception: pass
        for log in self.query(".ai-log"):
            try: _s(log, background=t.bg_main, color=t.text)
            except Exception: pass

        try:
            plasma = self.query_one("#plasma-animation", ReflectingAnimation)
            plasma.set_theme(t)
        except Exception:
            pass

        try:
            self._update_footer()
        except Exception:
            pass

        return True

    def _navigate_history(self, direction: int) -> None:
        """direction: -1 = older, +1 = newer."""
        if not self._input_history:
            return
        inp = self.query_one("#user-input", HistoryInput)
        if direction == -1:  # up — go back
            if self._history_index == -1:
                self._history_draft = inp.value
                self._history_index = len(self._input_history) - 1
            elif self._history_index > 0:
                self._history_index -= 1
        else:  # down — go forward
            if self._history_index == -1:
                return
            if self._history_index < len(self._input_history) - 1:
                self._history_index += 1
            else:
                self._history_index = -1
                inp.value = self._history_draft
                inp.cursor_position = len(self._history_draft)
                return
        entry = self._input_history[self._history_index]
        inp.value = entry
        inp.cursor_position = len(entry)

    def on_key(self, event: Key) -> None:
        if state.permissions.awaiting or state.permissions.awaiting_shell:
            if event.key == "up":
                self._navigate_permission_menu(-1)
            elif event.key == "down":
                self._navigate_permission_menu(1)
            elif event.key == "enter":
                # Handle Enter at app level so it works regardless of which widget has focus.
                # on_input_submitted has the same guard and is a no-op if called second.
                if state.permissions.awaiting_shell:
                    self._process_shell_permission_response("")
                else:
                    self._process_permission_response("")
            return
        if state.ui.mode == "THEME_SELECT":
            if event.key == "up":
                event.prevent_default()
                self._navigate_theme_menu(-1)
            elif event.key == "down":
                event.prevent_default()
                self._navigate_theme_menu(1)
            elif event.key == "enter":
                event.prevent_default()
                from chaosz.ui.app_rendering import confirm_theme_switch
                names = state.ui.theme_menu_names
                if names:
                    confirm_theme_switch(self, names[state.ui.theme_menu_index])
            return
        if state.ui.mode == "PLAN_APPROVE":
            if event.key == "up":
                event.prevent_default()
                self._navigate_plan_approval_menu(-1)
            elif event.key == "down":
                event.prevent_default()
                self._navigate_plan_approval_menu(1)
            elif event.key == "enter":
                event.prevent_default()
                from chaosz.ui.app_input_modes import _handle_mode_plan_approve
                _handle_mode_plan_approve(self)
            return
        if event.key == "escape":
            if state.ui.is_thinking:
                from chaosz.ui.app_ai_turn import request_cancel
                request_cancel()
                state.ui.plan_executing = False
                state.ui.plan_steps = []
                state.ui.plan_step_index = 0
                self._write("", Text("AI turn cancelled.", style="yellow dim"))
                return
            if state.ui.mode == "PERSONALITY_SET":
                self._confirm_personality()
            elif state.ui.mode == "SKILL_ADD":
                self._confirm_skill_add()
            elif state.ui.mode == "SKILL_MENU":
                state.ui.mode = "CHAT"
                self.query("#skill-menu").remove()
                self._set_input_label("You: ")
                self._set_status("Ready")
                self._write("", Text("Skill selection cancelled.", style="dim"))
            elif state.ui.mode == "THEME_SELECT":
                state.ui.mode = "CHAT"
                self.query("#theme-menu").remove()
                from chaosz.ui.app_rendering import _show_theme_input_area
                _show_theme_input_area(self)
                self._set_status("Ready")
                self._write("", Text("Theme selection cancelled.", style="dim"))
            elif state.ui.mode == "PLAN_APPROVE":
                state.ui.mode = "CHAT"
                self._hide_plan_approval_display()
                self._confirm_plan_approval("Reject")
            elif state.ui.mode in ("MODEL_SELECT", "MODEL_ADD_SELECT", "MODEL_SELECT_VERSION", "TEMP_SELECT"):
                state.provider.pending = ""
                state.ui.mode = "CHAT"
                self.query("#model-menu").remove()
                self._set_input_label("You: ")
                self._set_status("Ready")
                self._write("", Text("Model selection cancelled.", style="dim"))
            elif state.ui.mode == "MCP_SETUP":
                self._cancel_mcp_setup(self)
