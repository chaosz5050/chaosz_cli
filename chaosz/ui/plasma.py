import time
import math

from rich.text import Text
from textual.widgets import Static

ROWS = 5
_CHARS = [' ', ' ', '+', '=', '*', '+', '*', '#', '%', '#', '%', '#']

_DEFAULT_STOPS = ["#0a3d28", "#0f6e56", "#1acea0", "#5dffd0", "#aaffe8"]
_DEFAULT_BG    = "#0d0d0d"


def _color_from_stops(d: float, stops: list) -> str:
    if d < 0.2: return stops[0]
    if d < 0.4: return stops[1]
    if d < 0.6: return stops[2]
    if d < 0.8: return stops[3]
    return stops[4]


class ReflectingAnimation(Static):
    DEFAULT_CSS = """
    ReflectingAnimation {
        width: 1fr;
        height: 5;
        background: #0d0d0d;
        display: none;
    }
    """

    _timer = None

    def on_mount(self) -> None:
        from chaosz.ui.themes import get_theme
        t = get_theme()
        self._plasma_bg = t.plasma_bg
        self._plasma_stops = list(t.plasma_stops)
        self.styles.background = t.plasma_bg
        self._timer = self.set_interval(0.06, self.update_frame)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def set_theme(self, theme) -> None:
        self._plasma_bg = theme.plasma_bg
        self._plasma_stops = list(theme.plasma_stops)
        self.styles.background = theme.plasma_bg

    def update_frame(self) -> None:
        cols = self.size.width if self.size.width > 0 else 60
        bg = getattr(self, "_plasma_bg", _DEFAULT_BG)
        stops = getattr(self, "_plasma_stops", _DEFAULT_STOPS)
        t = time.monotonic() * 1000 * 0.0022
        text = Text()
        for row in range(ROWS):
            ny = row / ROWS
            for col in range(cols):
                nx = col / cols
                wave = (math.sin(nx * 7  - t * 1.4 + ny * 2) * 0.35
                      + math.sin(nx * 3  + t * 0.8 - ny * 3) * 0.30
                      + math.sin((nx + ny) * 5 - t * 1.1)    * 0.20
                      + math.sin(nx * 12 - t * 2.2 + ny)     * 0.15)
                norm = max(0.0, min(1.0, (wave + 1) / 2))
                char = _CHARS[int(norm * (len(_CHARS) - 1))]
                text.append(char, style=f"{_color_from_stops(norm, stops)} on {bg}")
            if row < ROWS - 1:
                text.append("\n")
        self.update(text)
