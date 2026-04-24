import json
import os
from dataclasses import dataclass

THEMES_DIR = os.path.join(os.path.expanduser("~/.config/chaosz"), "themes")

@dataclass
class Theme:
    name: str
    bg_main: str
    bg_input: str
    bg_statusbar: str
    bg_infobar: str
    header_text: str
    input_label: str
    scrollbar: str
    border: str
    text: str
    text_dim: str
    text_info: str
    text_version: str
    user_msg_bg: str
    plasma_bg: str
    plasma_stops: list
    cmd: str      # Rich markup color for command names
    arg: str      # Rich markup color for arguments/values
    accent: str   # Rich markup color for section headers
    menu_highlight: str = "#006666"  # background for selected menu items
    title_color: str = ""   # welcome line; empty = use header_text
    token_color: str = ""   # token count value; empty = use accent
    badge_color: str = ""   # plan/skill badges; empty = use accent


_BUILTIN_DATA: dict[str, dict] = {
    "default": {
        "bg_main": "#111111", "bg_input": "#1a1a1a", "bg_statusbar": "#222222",
        "bg_infobar": "#1a1a2e", "header_text": "#00ccaa", "input_label": "#4488ff",
        "scrollbar": "#555555", "border": "#2a2a2a",
        "text": "#ffffff", "text_dim": "#888888", "text_info": "#cccccc", "text_version": "#666666",
        "user_msg_bg": "#1a1a1a",
        "plasma_bg": "#0d0d0d",
        "plasma_stops": ["#0a3d28", "#0f6e56", "#1acea0", "#5dffd0", "#aaffe8"],
        "cmd": "purple", "arg": "green", "accent": "cyan", "menu_highlight": "#006666",
        "title_color": "#44bb66", "token_color": "yellow", "badge_color": "green",
    },
    "amber": {
        "bg_main": "#0d0800", "bg_input": "#1a1000", "bg_statusbar": "#150c00",
        "bg_infobar": "#1a1200", "header_text": "#ffb000", "input_label": "#cc8800",
        "scrollbar": "#664400", "border": "#2a1a00",
        "text": "#ffe090", "text_dim": "#997730", "text_info": "#ccaa60", "text_version": "#886622",
        "user_msg_bg": "#1a1000",
        "plasma_bg": "#0d0800",
        "plasma_stops": ["#3d1f00", "#7a3d00", "#cc7700", "#ffaa00", "#ffd080"],
        "cmd": "#dd8800", "arg": "#ffcc00", "accent": "#ffb000", "menu_highlight": "#553300",
    },
    "mono": {
        "bg_main": "#000000", "bg_input": "#111111", "bg_statusbar": "#0a0a0a",
        "bg_infobar": "#080808", "header_text": "#ffffff", "input_label": "#aaaaaa",
        "scrollbar": "#333333", "border": "#222222",
        "text": "#ffffff", "text_dim": "#666666", "text_info": "#aaaaaa", "text_version": "#555555",
        "user_msg_bg": "#111111",
        "plasma_bg": "#000000",
        "plasma_stops": ["#1a1a1a", "#333333", "#666666", "#aaaaaa", "#ffffff"],
        "cmd": "#cccccc", "arg": "#ffffff", "accent": "#ffffff", "menu_highlight": "#2a2a2a",
    },
    "green": {
        "bg_main": "#000800", "bg_input": "#001200", "bg_statusbar": "#000a00",
        "bg_infobar": "#000a00", "header_text": "#00ff41", "input_label": "#00cc33",
        "scrollbar": "#004400", "border": "#001a00",
        "text": "#00ff41", "text_dim": "#007722", "text_info": "#00cc33", "text_version": "#005500",
        "user_msg_bg": "#001200",
        "plasma_bg": "#000800",
        "plasma_stops": ["#001a00", "#003300", "#006600", "#00bb33", "#00ff41"],
        "cmd": "#00cc44", "arg": "#00ff41", "accent": "#00cc44", "menu_highlight": "#002200",
    },
}

# Always-valid default — used before files are seeded or when set_theme hasn't been called
_active: Theme = Theme(name="default", **_BUILTIN_DATA["default"])


def seed_builtin_themes() -> None:
    """Copy bundled .theme files to the user config dir if not already present."""
    os.makedirs(THEMES_DIR, exist_ok=True)
    try:
        from importlib.resources import files as _pkg_files
        pkg_themes = _pkg_files("chaosz.ui.theme_files")
        for item in pkg_themes.iterdir():
            if item.name.endswith(".theme"):
                dest = os.path.join(THEMES_DIR, item.name)
                if not os.path.exists(dest):
                    with open(dest, "w", encoding="utf-8") as f:
                        f.write(item.read_text(encoding="utf-8"))
        return
    except Exception:
        pass
    # Fallback: generate from _BUILTIN_DATA (editable/dev installs without package data)
    for name, data in _BUILTIN_DATA.items():
        path = os.path.join(THEMES_DIR, f"{name}.theme")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)


def list_themes() -> list[str]:
    """Return sorted list of theme names from the themes directory."""
    if not os.path.isdir(THEMES_DIR):
        return list(_BUILTIN_DATA.keys())
    names = [
        fname[:-6]
        for fname in sorted(os.listdir(THEMES_DIR))
        if fname.endswith(".theme")
    ]
    return names or list(_BUILTIN_DATA.keys())


def load_theme_file(name: str) -> "Theme | None":
    path = os.path.join(THEMES_DIR, f"{name}.theme")
    try:
        with open(path) as f:
            data = json.load(f)
        fallback = _BUILTIN_DATA.get(name, _BUILTIN_DATA["default"])
        merged = {**fallback, **data}
        return Theme(name=name, **merged)
    except Exception:
        if name in _BUILTIN_DATA:
            return Theme(name=name, **_BUILTIN_DATA[name])
        return None


def get_theme() -> Theme:
    return _active


def set_theme(name: str) -> bool:
    global _active
    t = load_theme_file(name)
    if t is None:
        return False
    _active = t
    return True
