import threading

from textual.containers import VerticalScroll
from textual.widgets import Static

from chaosz.state import state

_GLITCH_FRAMES = ["█", "▓", "▒", "░", "▒", "▓"]


def _update_status_bar(app) -> None:
    """Helper to update the status bar based on both thinking and reflecting states."""
    parts = []
    
    # Use the appropriate glitch frame (preferring the thinking one if both active)
    glitch_idx = getattr(app, "_glitch_frame_idx", 0)
    reflect_idx = getattr(app, "_reflect_frame_idx", 0)
    frame = _GLITCH_FRAMES[glitch_idx if state.ui.is_thinking else reflect_idx]

    if state.ui.is_thinking:
        if state.permissions.awaiting or state.permissions.awaiting_shell:
            parts.append("Waiting for your input...")
        else:
            parts.append("Thinking... (Esc to cancel)")
    
    if state.background.reflection_active:
        parts.append("░▒▓ REFLECTING ▓▒░")
    
    if not parts:
        # If we are in the middle of a special mode (like EXIT_CONFIRM), don't overwrite it with Ready
        # but for now, the app seems to use _set_status for mode hints too.
        # We only return to Ready if no background tasks are running.
        app._set_status("Ready")
        return

    status_text = f"[dim]▶[/dim] {frame} " + " | ".join(parts)
    app.query_one("#status-bar", Static).update(status_text)


def start_glitch(app) -> None:
    app._glitch_frame_idx = 0
    _update_status_bar(app)
    app._glitch_timer = app.set_interval(0.12, app._tick_glitch)
    app._mount_plasma()


def tick_glitch(app) -> None:
    app._glitch_frame_idx = (app._glitch_frame_idx + 1) % len(_GLITCH_FRAMES)
    _update_status_bar(app)


def stop_glitch(app) -> None:
    app._unmount_plasma()
    if app._glitch_timer is not None:
        app._glitch_timer.stop()
        app._glitch_timer = None
    _update_status_bar(app)


def mount_plasma(app) -> None:
    app._current_log = None  # next _write() creates a fresh log after the animation
    try:
        app.query_one("#plasma-animation").styles.display = "block"
        app.query_one("#input-label").styles.display = "none"
        app.query_one("#user-input").styles.display = "none"
    except Exception:
        pass


def unmount_plasma(app) -> None:
    try:
        app.query_one("#plasma-animation").styles.display = "none"
        app.query_one("#input-label").styles.display = "block"
        app.query_one("#user-input").styles.display = "block"
    except Exception:
        pass


def start_reflect_glitch(app) -> None:
    app._reflect_frame_idx = 0
    _update_status_bar(app)
    app._reflect_timer = app.set_interval(0.12, app._tick_reflect_glitch)


def tick_reflect_glitch(app) -> None:
    app._reflect_frame_idx = (app._reflect_frame_idx + 1) % len(_GLITCH_FRAMES)
    _update_status_bar(app)


def stop_reflect_glitch(app) -> None:
    if app._reflect_timer is not None:
        app._reflect_timer.stop()
        app._reflect_timer = None
    _update_status_bar(app)
