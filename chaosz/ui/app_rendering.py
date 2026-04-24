import re

from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import RichLog, Static

from chaosz.providers import PROVIDER_REGISTRY, load_providers, save_providers, sync_runtime_provider_state
from chaosz.state import state
from chaosz.ui.themes import get_theme

TEMPERATURE_OPTIONS = [
    (0.15, "Coding / Tools"),
    (0.30, "Precise"),
    (0.70, "Balanced"),
    (1.00, "Creative"),
    (1.30, "Wild"),
]

KEEP_CURRENT_SENTINEL = "[keep current model]"


def get_or_create_log(app) -> RichLog:
    if app._current_log is None:
        log = RichLog(wrap=True, highlight=False, markup=False, classes="ai-log")
        app.query_one("#chat-scroll", VerticalScroll).mount(log)
        app._current_log = log
    return app._current_log


def write(app, _label: str, content) -> None:
    """Write a single Rich renderable to the chat log."""
    get_or_create_log(app).write(content)
    app.query_one("#chat-scroll", VerticalScroll).scroll_end(animate=False)


def set_status(app, message: str) -> None:
    app.query_one("#status-bar", Static).update(f"[dim]▶[/dim] {message}")


def set_input_label(app, markup: str) -> None:
    app.query_one("#input-label", Static).update(markup)


def update_footer(app) -> None:
    t = get_theme()
    if state.ui.ctx_estimated_tokens > 0:
        # Use the api_msgs-based estimate kept in sync during AI turns — includes
        # the system prompt and all tool results, so matches what triggers auto-compact.
        estimated = state.ui.ctx_estimated_tokens
    else:
        # Fallback between turns: estimate from state.session.messages only.
        msg_chars = sum(len(m.get("content", "")) for m in state.session.messages if m.get("content"))
        estimated = msg_chars // 4
    ratio = estimated / state.provider.max_ctx if state.provider.max_ctx > 0 else 0
    if ratio > 0.9:
        ctx_color = "red"
    elif ratio > 0.7:
        ctx_color = "yellow"
    else:
        ctx_color = t.accent
    ctx_max = f"{state.provider.max_ctx // 1000}K" if state.provider.max_ctx >= 1000 else str(state.provider.max_ctx)
    token_color = t.token_color or t.accent
    badge_color = t.badge_color or t.accent
    tokens_str = f"[bold]Tokens:[/bold] [{token_color}]{state.session.tokens}[/]"
    if state.session.cached_tokens:
        tokens_str += f" [dim]({state.session.cached_tokens} cached)[/dim]"

    plan_badge = f" [bold {badge_color}]│ PLAN[/]" if state.ui.plan_mode else ""
    skill_badge = f" [bold {badge_color}]│ {state.reasoning.active_skill}[/]" if state.reasoning.active_skill else ""
    personality_badge = " [dim]│ ✦ persona[/dim]" if state.reasoning.personality else ""
    app.query_one("#info-bar", Static).update(
        f" [bold]Model:[/bold] [{t.accent}]{state.provider.active}[/][dim]/[/dim][{t.accent}]{state.provider.model}[/] │ "
        f"{tokens_str} │ "
        f"[bold]Context:[/bold] [{ctx_color}]{ratio * 100:.1f}% of {ctx_max}[/{ctx_color}]"
        f"{plan_badge}"
        f"{skill_badge}"
        f"{personality_badge}"
        f"  [dim](/help for commands)[/dim]"
    )


def write_ai_turn(app, text: str) -> None:
    """Render a complete AI turn: ● prefix inline on first line, or alone before structural markdown."""
    app._current_log = None  # force new RichLog for each AI turn
    log = get_or_create_log(app)
    log.write(Text(""))

    stripped = text.strip()
    structural = bool(re.match(r'^(#{1,6} |[-*+>|]|\d+\. |```)', stripped))

    t = get_theme()
    dot = Text()
    dot.append("● ", style=f"bold {t.accent}")

    if structural:
        log.write(dot)
        render_ai_text(app, text)
    else:
        first_newline = stripped.find("\n")
        if first_newline == -1:
            first_line, rest = stripped, ""
        else:
            first_line, rest = stripped[:first_newline], stripped[first_newline + 1 :]

        inline = Text()
        inline.append("● ", style=f"bold {t.accent}")
        inline.append(first_line)
        log.write(inline)

        if rest.strip():
            render_ai_text(app, rest)

    log.write(Text(""))
    app.call_after_refresh(app.query_one("#chat-scroll", VerticalScroll).scroll_end, animate=False)


def render_ai_text(app, text: str) -> None:
    """Split AI text on code fences; render Python/Shell with Syntax, rest as Markdown."""
    log = get_or_create_log(app)
    parts = re.split(r"(```(?:\w+)?\n?[\s\S]*?```)", text)
    for part in parts:
        if not part:
            continue
        m = re.match(r"```(\w*)\n?([\s\S]*?)```", part)
        if m:
            lang = m.group(1).lower().strip()
            code = m.group(2).rstrip("\n")
            if lang in ("python", "bash", "sh"):
                highlight_lang = "bash" if lang == "sh" else lang
                log.write(
                    Syntax(
                        code,
                        highlight_lang,
                        theme="monokai",
                        background_color="default",
                        padding=(0, 1),
                        word_wrap=True,
                    )
                )
            else:
                log.write(
                    Panel(
                        Text(code, style="dim white"),
                        border_style="#444444",
                        padding=(0, 1),
                    )
                )
        else:
            stripped = part.strip()
            if stripped:
                log.write(Markdown(stripped))


def start_reasoning_block(app) -> None:
    """Create a new log entry with the ◦ thinking... header."""
    app._current_log = None  # new RichLog entry
    log = get_or_create_log(app)
    log.write(Text(""))
    header = Text()
    header.append("◦ ", style=f"dim {get_theme().accent}")
    header.append("thinking...", style="dim italic")
    log.write(header)


def append_reasoning_line(app, text: str) -> None:
    """Write one line of reasoning text in dim style."""
    log = get_or_create_log(app)
    log.write(Text("  " + text, style="dim"))
    app.query_one("#chat-scroll", VerticalScroll).scroll_end(animate=False)


def end_reasoning_block(app) -> None:
    """Write the separator line that closes the reasoning block."""
    log = get_or_create_log(app)
    log.write(Text(""))
    log.write(Text("  " + "─" * 38, style="dim"))


def write_reasoning_block(app, text: str) -> None:
    """Write a complete reasoning block at once (for <think> tag post-processing)."""
    start_reasoning_block(app)
    for line in text.split("\n"):
        append_reasoning_line(app, line)
    end_reasoning_block(app)


def _build_menu_text(providers, active, names, bar_width, max_name) -> Text:
    """Build the full menu as a single multi-line Text for the #model-menu Static widget."""
    t = get_theme()
    text = Text()
    title = "  SELECT PROVIDER" if state.ui.mode == "MODEL_SELECT" else "  ADD PROVIDER"
    text.append(title, style=f"bold {t.accent}")
    text.append("   ↑/↓ navigate   Enter confirm   Esc cancel\n", style="dim")
    text.append("    " + "─" * bar_width + "\n", style=f"dim {t.accent}")
    for i, name in enumerate(names):
        suffix = ""
        if state.ui.mode == "MODEL_SELECT":
            pdata = providers.get(name, {})
            model_label = pdata.get("model", "?")
            active_suffix = " (active)" if name == active else ""
            bar_text = f"{name:<{max_name}}  {model_label}{active_suffix}"
        else:
            # MODEL_ADD_SELECT mode: show all in registry
            reg = PROVIDER_REGISTRY.get(name, {})
            model_label = reg.get("model", "?")
            # If already configured, show a hint
            if name in providers:
                suffix = " (configured)"
            bar_text = f"{name:<{max_name}}  {model_label}{suffix}"

        bar_text = bar_text.ljust(bar_width)[:bar_width]
        if i == state.provider.menu_index:
            text.append("  ▶ ", style=f"bold {t.accent}")
            text.append(bar_text, style=f"bold white on {t.menu_highlight}")
        else:
            text.append("    ")
            text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("    " + "─" * bar_width, style=f"dim {t.accent}")
    return text


def render_model_menu(app) -> None:
    """Mount a provider selection menu Static below the last chat message."""
    providers, active = load_providers()
    if state.ui.mode == "MODEL_SELECT":
        names = list(providers.keys())
    else:
        # Show all available providers from registry for "add"
        names = list(PROVIDER_REGISTRY.keys())

    state.provider.menu_providers = names
    if not names:
        app._write("", Text("No providers available.", style="yellow"))
        return

    max_name = max(len(n) for n in names)
    if state.ui.mode == "MODEL_SELECT":
        max_model = max(len(providers[n].get("model", "?")) for n in names)
        bar_width = max_name + 2 + max_model + len(" (active)") + 2
    else:
        max_model = max(len(PROVIDER_REGISTRY[n].get("model", "?")) for n in names)
        bar_width = max_name + 2 + max_model + len(" (configured)") + 2

    text = _build_menu_text(providers, active, names, bar_width, max_name)
    # Remove any stale menu widget before mounting a fresh one
    app.query("#model-menu").remove()
    scroll = app.query_one("#chat-scroll", VerticalScroll)
    scroll.mount(Static(text, id="model-menu"))
    scroll.scroll_end(animate=False)


def navigate_model_menu(app, direction: int) -> None:
    n = len(state.provider.menu_providers)
    if n == 0:
        return
    state.provider.menu_index = (state.provider.menu_index + direction) % n
    providers, active = load_providers()
    names = state.provider.menu_providers
    max_name = max(len(n) for n in names)
    if state.ui.mode == "MODEL_SELECT":
        max_model = max(len(providers[n].get("model", "?")) for n in names)
        bar_width = max_name + 2 + max_model + len(" (active)") + 2
    else:
        max_model = max(len(PROVIDER_REGISTRY[n].get("model", "?")) for n in names)
        bar_width = max_name + 2 + max_model + len(" (configured)") + 2

    text = _build_menu_text(providers, active, names, bar_width, max_name)
    menus = app.query("#model-menu")
    if menus:
        menus.first().update(text)


def confirm_model_switch(app, provider: str) -> None:
    import threading
    providers, _ = load_providers()
    if provider not in providers:
        app._write("", Text(f"Provider '{provider}' not configured.", style="red"))
        app.query("#model-menu").remove()
        state.ui.mode = "CHAT"
        app._set_input_label("You: ")
        app._set_status("Ready")
        return
    pdata = providers[provider]
    save_providers(providers, provider)
    sync_runtime_provider_state(provider, providers)
    state.ui.ctx_estimated_tokens = 0
    app._update_footer()
    app._write("", Text(f"Switched to {provider}. Fetching model versions...", style="dim"))
    app._set_status("Fetching models...")

    def _fetch():
        from chaosz.providers import get_available_models
        try:
            models = get_available_models(provider)
            all_models = [KEEP_CURRENT_SENTINEL] + models
            state.provider.available_models = all_models
            state.provider.available_models_index = 0

            def _render():
                if not models:
                    app._write("", Text(f"No models found for {provider}.", style="yellow"))
                    app.query("#model-menu").remove()
                    state.ui.mode = "CHAT"
                    app._set_input_label("You: ")
                    app._set_status("Ready")
                else:
                    state.ui.mode = "MODEL_SELECT_VERSION"
                    app._set_input_label(f"[bold {get_theme().accent}] VERSION: [/] ")
                    app._set_status("↑/↓ navigate   Enter confirm   Esc cancel")
                    app._render_model_version_menu()
            app.call_from_thread(_render)
        except Exception as e:
            def _err():
                app._write("", Text(f"Error fetching models: {e}", style="red"))
                app.query("#model-menu").remove()
                state.ui.mode = "CHAT"
                app._set_input_label("You: ")
                app._set_status("Ready")
            app.call_from_thread(_err)

    threading.Thread(target=_fetch, daemon=True).start()


def _build_version_menu_text(models, active_model, bar_width) -> Text:
    t = get_theme()
    text = Text()
    text.append("  SELECT MODEL VERSION", style=f"bold {t.accent}")
    text.append("   ↑/↓ navigate   Enter confirm   Esc cancel\n", style="dim")
    text.append("    " + "─" * bar_width + "\n", style=f"dim {t.accent}")
    for i, name in enumerate(models):
        is_sentinel = (name == KEEP_CURRENT_SENTINEL)
        if is_sentinel:
            bar_text = name.ljust(bar_width)[:bar_width]
            if i == state.provider.available_models_index:
                text.append("  ▶ ", style=f"bold {t.accent}")
                text.append(bar_text, style=f"bold {t.accent} on {t.menu_highlight}")
            else:
                text.append("    ")
                text.append(bar_text, style=f"dim {t.accent}")
        else:
            suffix = " (active)" if name == active_model else ""
            bar_text = f"{name}{suffix}".ljust(bar_width)[:bar_width]
            if i == state.provider.available_models_index:
                text.append("  ▶ ", style=f"bold {t.accent}")
                text.append(bar_text, style=f"bold white on {t.menu_highlight}")
            else:
                text.append("    ")
                text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("    " + "─" * bar_width, style=f"dim {t.accent}")
    return text


def render_model_version_menu(app) -> None:
    models = state.provider.available_models
    if not models:
        app._write("", Text("No models found for this provider.", style="yellow"))
        state.ui.mode = "CHAT"
        return

    max_len = max(len(m) for m in models)
    bar_width = max_len + len(" (active)") + 2
    text = _build_version_menu_text(models, state.provider.model, bar_width)

    existing = app.query("#model-menu")
    scroll = app.query_one("#chat-scroll", VerticalScroll)
    if existing:
        existing.first().update(text)
    else:
        scroll.mount(Static(text, id="model-menu"))
    scroll.scroll_end(animate=False)


def navigate_model_version_menu(app, direction: int) -> None:
    n = len(state.provider.available_models)
    if n == 0:
        return
    state.provider.available_models_index = (state.provider.available_models_index + direction) % n
    max_len = max(len(m) for m in state.provider.available_models)
    bar_width = max_len + len(" (active)") + 2
    text = _build_version_menu_text(state.provider.available_models, state.provider.model, bar_width)
    menus = app.query("#model-menu")
    if menus:
        menus.first().update(text)


def _build_two_column_menu_text(models, active_model, pre_selected_model, left_col_width) -> Text:
    """Render model list (left) and temperature options (right) side by side."""
    t = get_theme()
    text = Text()

    # Build left column lines as (plain_str, styled_segments) pairs
    # We render each line as fixed-width so the right column aligns neatly
    header_left = "  SELECT MODEL VERSION"
    sep_left = "    " + "─" * left_col_width

    right_header = "  SELECT TEMPERATURE"
    right_sep = "    " + "─" * 28
    right_hint = "   ↑/↓ navigate   Enter confirm"

    # Header line
    text.append(header_left.ljust(left_col_width + 4), style=f"bold {t.accent}")
    text.append("  │  ")
    text.append(right_header, style=f"bold {t.accent}")
    text.append("\n")

    # Hint line (left blank, right has hint)
    text.append(" " * (left_col_width + 4))
    text.append("  │  ")
    text.append(right_hint, style="dim")
    text.append("\n")

    # Separator line
    text.append(sep_left, style=f"dim {t.accent}")
    text.append("  │  ")
    text.append(right_sep, style=f"dim {t.accent}")
    text.append("\n")

    # Data rows — zip model rows with temperature rows
    right_rows = []
    for i, (temp_val, temp_label) in enumerate(TEMPERATURE_OPTIONS):
        right_rows.append((i, temp_val, temp_label))

    max_rows = max(len(models), len(right_rows))

    for row in range(max_rows):
        # Left column
        if row < len(models):
            name = models[row]
            is_pre_selected = (name == pre_selected_model)
            suffix = " (active)" if name == active_model else ""
            bar_text = f"{name}{suffix}".ljust(left_col_width)[:left_col_width]
            if is_pre_selected:
                text.append("  ✓ ", style="bold green")
                text.append(bar_text, style="bold green")
            else:
                text.append("    ")
                text.append(bar_text, style="dim white")
        else:
            text.append(" " * (left_col_width + 4))

        text.append("  │  ")

        # Right column
        if row < len(right_rows):
            i, temp_val, temp_label = right_rows[row]
            right_text = f"{temp_val:.2f}  {temp_label}"
            if i == state.provider.temp_menu_index:
                text.append("  ▶ ", style=f"bold {t.accent}")
                text.append(right_text, style=f"bold white on {t.menu_highlight}")
            else:
                text.append("    ")
                text.append(right_text, style="dim white")

        text.append("\n")

    # Bottom separators
    text.append(sep_left, style=f"dim {t.accent}")
    text.append("  │  ")
    text.append(right_sep, style=f"dim {t.accent}")
    return text


def render_temp_select_menu(app, pre_selected_model: str) -> None:
    state.provider.pending = pre_selected_model
    # Default cursor to closest matching temperature option
    closest = min(
        range(len(TEMPERATURE_OPTIONS)),
        key=lambda i: abs(TEMPERATURE_OPTIONS[i][0] - state.provider.temperature)
    )
    state.provider.temp_menu_index = closest

    models = [m for m in state.provider.available_models if m != KEEP_CURRENT_SENTINEL]
    max_len = max(len(m) for m in models)
    left_col_width = max_len + len(" (active)") + 2
    text = _build_two_column_menu_text(models, state.provider.model, pre_selected_model, left_col_width)
    menus = app.query("#model-menu")
    if menus:
        menus.first().update(text)


def navigate_temp_menu(app, direction: int) -> None:
    state.provider.temp_menu_index = (state.provider.temp_menu_index + direction) % len(TEMPERATURE_OPTIONS)
    models = [m for m in state.provider.available_models if m != KEEP_CURRENT_SENTINEL]
    max_len = max(len(m) for m in models)
    left_col_width = max_len + len(" (active)") + 2
    text = _build_two_column_menu_text(
        models, state.provider.model, state.provider.pending, left_col_width
    )
    menus = app.query("#model-menu")
    if menus:
        menus.first().update(text)


def _build_skill_menu_text(names: list[str], active_skill: str | None) -> Text:
    t = get_theme()
    all_entries = ["none"] + names
    max_len = max((len(e) for e in all_entries), default=4)
    bar_width = max_len + len(" (active)") + 2
    text = Text()
    text.append("  SELECT SKILL", style=f"bold {t.accent}")
    text.append("   ↑/↓ navigate   Enter confirm   Esc cancel\n", style="dim")
    text.append("    " + "─" * bar_width + "\n", style=f"dim {t.accent}")
    for i, name in enumerate(all_entries):
        is_active = (name == "none" and not active_skill) or (name == active_skill)
        suffix = " (active)" if is_active else ""
        bar_text = f"{name}{suffix}".ljust(bar_width)[:bar_width]
        if i == state.ui.skill_menu_index:
            text.append("  ▶ ", style=f"bold {t.accent}")
            text.append(bar_text, style=f"bold white on {t.menu_highlight}")
        else:
            text.append("    ")
            text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("    " + "─" * bar_width, style=f"dim {t.accent}")
    return text


def render_skill_menu(app) -> None:
    from chaosz.skills import list_skills
    names = list_skills()
    state.ui.skill_menu_names = names
    all_entries = ["none"] + names
    # Pre-select the currently active skill
    if state.reasoning.active_skill and state.reasoning.active_skill in all_entries:
        state.ui.skill_menu_index = all_entries.index(state.reasoning.active_skill)
    else:
        state.ui.skill_menu_index = 0

    text = _build_skill_menu_text(names, state.reasoning.active_skill)
    app.query("#skill-menu").remove()
    scroll = app.query_one("#chat-scroll", VerticalScroll)
    scroll.mount(Static(text, id="skill-menu"))
    scroll.scroll_end(animate=False)


def navigate_skill_menu(app, direction: int) -> None:
    total = len(state.ui.skill_menu_names) + 1  # +1 for "none"
    if total == 0:
        return
    state.ui.skill_menu_index = (state.ui.skill_menu_index + direction) % total
    text = _build_skill_menu_text(state.ui.skill_menu_names, state.reasoning.active_skill)
    menus = app.query("#skill-menu")
    if menus:
        menus.first().update(text)


def _build_theme_menu_text(names: list[str], active_name: str) -> Text:
    t = get_theme()
    max_len = max((len(n) for n in names), default=7)
    bar_width = max_len + len(" (active)") + 2
    text = Text()
    text.append("  SELECT THEME", style=f"bold {t.accent}")
    text.append("   ↑/↓ navigate   Enter confirm   Esc cancel\n", style="dim")
    text.append("    " + "─" * bar_width + "\n", style=f"dim {t.accent}")
    for i, name in enumerate(names):
        suffix = " (active)" if name == active_name else ""
        bar_text = f"{name}{suffix}".ljust(bar_width)[:bar_width]
        if i == state.ui.theme_menu_index:
            text.append("  ▶ ", style=f"bold {t.accent}")
            text.append(bar_text, style=f"bold white on {t.menu_highlight}")
        else:
            text.append("    ")
            text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("    " + "─" * bar_width, style=f"dim {t.accent}")
    return text


def _show_theme_input_area(app) -> None:
    app.query_one("#input-label").styles.display = "block"
    app.query_one("#user-input").styles.display = "block"
    set_input_label(app, "You: ")
    app.query_one("#user-input").focus()


def render_theme_menu(app) -> None:
    from chaosz.ui.themes import list_themes, get_theme
    names = list_themes()
    state.ui.theme_menu_names = names
    active_name = get_theme().name
    if active_name in names:
        state.ui.theme_menu_index = names.index(active_name)
    else:
        state.ui.theme_menu_index = 0
    text = _build_theme_menu_text(names, active_name)
    app.query("#theme-menu").remove()
    scroll = app.query_one("#chat-scroll", VerticalScroll)
    scroll.mount(Static(text, id="theme-menu"))
    scroll.scroll_end(animate=False)
    # Hide the input row while the menu is active; keep focus on input so
    # HistoryInput.on_key() still receives arrow keys (same as permission display)
    app.query_one("#input-label").styles.display = "none"
    app.query_one("#user-input").styles.display = "none"
    app.query_one("#user-input").focus()
    set_status(app, "↑/↓ navigate   Enter confirm   Esc cancel")


def navigate_theme_menu(app, direction: int) -> None:
    n = len(state.ui.theme_menu_names)
    if n == 0:
        return
    state.ui.theme_menu_index = (state.ui.theme_menu_index + direction) % n
    from chaosz.ui.themes import get_theme
    text = _build_theme_menu_text(state.ui.theme_menu_names, get_theme().name)
    menus = app.query("#theme-menu")
    if menus:
        menus.first().update(text)


def confirm_theme_switch(app, name: str) -> None:
    from chaosz.config import save_theme
    app.query("#theme-menu").remove()
    state.ui.mode = "CHAT"
    _show_theme_input_area(app)
    set_status(app, "Ready")
    if app.apply_theme(name):
        save_theme(name)
        app._write("", Text(f"Theme '{name}' applied.", style="dim"))
    else:
        app._write("", Text(f"Theme '{name}' not found.", style="red"))


_PERMISSION_OPTIONS_FULL = [
    ("Yes",             "allow once"),
    ("Yes for session", "allow for the rest of this session"),
    ("No",              "deny"),
]
_PERMISSION_OPTIONS_SHORT = [
    ("Yes", "allow this command"),
    ("No",  "deny"),
]


def _build_permission_text(options: list) -> Text:
    t = get_theme()
    text = Text()
    text.append("  ────────────────────────────────────────\n", style=f"dim {t.accent}")
    for i, (label, desc) in enumerate(options):
        bar_text = f"{label:<16} {desc}"
        if i == state.permissions.approval_index:
            text.append("  ▶ ", style=f"bold {t.accent}")
            text.append(bar_text, style=f"bold white on {t.menu_highlight}")
        else:
            text.append("    ")
            text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("  ────────────────────────────────────────", style=f"dim {t.accent}")
    return text


def show_permission_display(app, options: list, status_msg: str) -> None:
    state.permissions.approval_index = 0
    state.permissions.approval_option_count = len(options)
    app.query_one("#permission-display", Static).update(_build_permission_text(options))
    app.query_one("#permission-display").styles.display = "block"
    app.query_one("#input-label").styles.display = "none"
    app.query_one("#user-input").styles.display = "none"
    t = get_theme()
    app.query_one("#status-bar", Static).update(
        f"[bold {t.accent}]{status_msg}[/]"
        "  [dim]↑/↓ navigate   Enter confirm[/dim]"
    )
    app.query_one("#user-input").focus()


def hide_permission_display(app) -> None:
    app.query_one("#permission-display").styles.display = "none"
    app.query_one("#input-label").styles.display = "block"
    app.query_one("#user-input").styles.display = "block"
    set_input_label(app, "You: ")


def navigate_permission_menu(app, direction: int) -> None:
    n = state.permissions.approval_option_count
    state.permissions.approval_index = (state.permissions.approval_index + direction) % n
    options = (
        _PERMISSION_OPTIONS_SHORT if n == 2 else _PERMISSION_OPTIONS_FULL
    )
    app.query_one("#permission-display", Static).update(_build_permission_text(options))


_PLAN_APPROVAL_OPTIONS = ["Approve", "Discuss", "Reject"]
_PLAN_APPROVAL_DESCRIPTIONS = {
    "Approve": "execute the plan now",
    "Discuss": "give feedback to revise the plan",
    "Reject":  "cancel the plan",
}


def _build_plan_approval_text() -> Text:
    t = get_theme()
    text = Text()
    text.append("  ────────────────────────────────────────\n", style=f"dim {t.accent}")
    for i, opt in enumerate(_PLAN_APPROVAL_OPTIONS):
        desc = _PLAN_APPROVAL_DESCRIPTIONS[opt]
        bar_text = f"{opt:<10} {desc}"
        if i == state.ui.plan_approval_index:
            text.append("  ▶ ", style=f"bold {t.accent}")
            text.append(bar_text, style=f"bold white on {t.menu_highlight}")
        else:
            text.append("    ")
            text.append(bar_text, style="dim white")
        text.append("\n")
    text.append("  ────────────────────────────────────────", style=f"dim {t.accent}")
    return text


def show_plan_approval_display(app) -> None:
    app.query_one("#plan-approval-display").styles.display = "block"
    app.query_one("#input-label").styles.display = "none"
    app.query_one("#user-input").styles.display = "none"
    t = get_theme()
    app.query_one("#status-bar", Static).update(
        f"[bold {t.accent}]PLAN APPROVAL[/]"
        "  [dim]↑/↓ navigate   Enter confirm   Esc reject[/dim]"
    )


def hide_plan_approval_display(app) -> None:
    app.query_one("#plan-approval-display").styles.display = "none"
    app.query_one("#input-label").styles.display = "block"
    app.query_one("#user-input").styles.display = "block"
    set_status(app, "Ready")
    set_input_label(app, "You: ")
    app.query_one("#user-input").focus()


def render_plan_approval_menu(app) -> None:
    state.ui.plan_approval_index = 0
    app.query_one("#plan-approval-display", Static).update(_build_plan_approval_text())
    show_plan_approval_display(app)


def navigate_plan_approval_menu(app, direction: int) -> None:
    state.ui.plan_approval_index = (state.ui.plan_approval_index + direction) % len(_PLAN_APPROVAL_OPTIONS)
    app.query_one("#plan-approval-display", Static).update(_build_plan_approval_text())


def confirm_plan_approval(app, choice: str) -> None:
    if choice == "Approve":
        steps = state.ui.plan_steps
        if not steps:
            app._write("", Text("No plan steps to execute.", style="red"))
            return
        state.ui.plan_step_index = 0
        state.ui.plan_executing = True
        from chaosz.plan_driver import build_step_prompt
        from chaosz.session import append_to_live_session
        prompt = build_step_prompt(0, steps, state.ui.plan_goal)
        state.session.messages.append({"role": "user", "content": prompt})
        append_to_live_session("user", prompt)
        app._write("", Text(f"▶ Step 1/{len(steps)}", style=f"dim {get_theme().accent}"))
        app._run_routed_turn(prompt)

    elif choice == "Discuss":
        state.ui.plan_steps = []
        state.ui.plan_goal = ""
        state.ui.plan_executing = False
        app._write(
            "",
            Text.from_markup("[dim]Type your feedback — the AI will revise the plan.[/dim]"),
        )
        app._set_status("Ready")
        app.query_one("#user-input").focus()

    elif choice == "Reject":
        state.ui.plan_steps = []
        state.ui.plan_goal = ""
        state.ui.plan_executing = False
        state.ui.plan_mode_this_turn = False
        app._write("", Text("Plan rejected.", style="dim red"))
        app._set_status("Ready")
        app.query_one("#user-input").focus()


def confirm_model_version_switch(app, model_name: str, temperature: float | None = None) -> None:
    providers, active = load_providers()
    if active not in providers:
        return
    providers[active]["model"] = model_name
    if temperature is not None:
        providers[active]["temperature"] = temperature
    save_providers(providers, active)
    # Re-query context window for Ollama — it's model-specific
    if active == "ollama":
        from chaosz.ollama_utils import get_model_context_window
        ctx = get_model_context_window(model_name)
        providers["ollama"]["context_window"] = ctx
        save_providers(providers, active)
    sync_runtime_provider_state(active, providers)

    if temperature is not None:
        _, temp_label = TEMPERATURE_OPTIONS[state.provider.temp_menu_index]
        app._write("", Text(f"Model: {model_name}  |  Temperature: {temperature:.2f} ({temp_label})", style="green"))
    else:
        app._write("", Text(f"Model version updated: {model_name}", style="green"))
    app._update_footer()
