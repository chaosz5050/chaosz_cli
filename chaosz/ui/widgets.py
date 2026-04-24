import re

from textual.widgets import Input
from textual.events import Key, Paste

from chaosz.state import state


class HistoryInput(Input):
    """Input that intercepts ↑/↓ before the widget can act on them."""

    def on_key(self, event: Key) -> None:
        if state.permissions.awaiting or state.permissions.awaiting_shell:
            event.prevent_default()
            return
        if state.ui.mode in ("MODEL_SELECT", "MODEL_ADD_SELECT", "MODEL_SELECT_VERSION", "TEMP_SELECT", "SKILL_MENU", "THEME_SELECT", "PLAN_APPROVE"):
            if event.key == "up":
                event.prevent_default()
                if state.ui.mode == "MODEL_SELECT_VERSION":
                    self.app._navigate_model_version_menu(-1)
                elif state.ui.mode == "TEMP_SELECT":
                    self.app._navigate_temp_menu(-1)
                elif state.ui.mode == "SKILL_MENU":
                    self.app._navigate_skill_menu(-1)
                elif state.ui.mode == "THEME_SELECT":
                    self.app._navigate_theme_menu(-1)
                elif state.ui.mode == "PLAN_APPROVE":
                    self.app._navigate_plan_approval_menu(-1)
                else:
                    self.app._navigate_model_menu(-1)
            elif event.key == "down":
                event.prevent_default()
                if state.ui.mode == "MODEL_SELECT_VERSION":
                    self.app._navigate_model_version_menu(1)
                elif state.ui.mode == "TEMP_SELECT":
                    self.app._navigate_temp_menu(1)
                elif state.ui.mode == "SKILL_MENU":
                    self.app._navigate_skill_menu(1)
                elif state.ui.mode == "THEME_SELECT":
                    self.app._navigate_theme_menu(1)
                elif state.ui.mode == "PLAN_APPROVE":
                    self.app._navigate_plan_approval_menu(1)
                else:
                    self.app._navigate_model_menu(1)
            return  # don't fall through to history navigation
        if event.key == "up":
            event.prevent_default()
            self.app._navigate_history(-1)
        elif event.key == "down":
            event.prevent_default()
            self.app._navigate_history(1)

    def on_paste(self, event: Paste) -> None:
        event.prevent_default()
        cleaned = " ".join(line.strip() for line in event.text.splitlines() if line.strip())
        cleaned = re.sub(r" +", " ", cleaned)
        self.insert_text_at_cursor(cleaned)
