import re

from chaosz.state import state

APPROVAL_WORDS = {
    "yes", "go", "ok", "sure", "yep", "proceed", "execute",
    "run it", "go ahead", "do it", "confirm", "approved", "sounds good",
}


def parse_plan_steps(text: str) -> list[str]:
    """Extract numbered steps from an AI plan response."""
    return re.findall(r'^\s*\d+[\.\)]\s+(.+)', text, re.MULTILINE)


def is_plan_approval(user_input: str) -> bool:
    """True if the user message looks like a plan approval."""
    lowered = user_input.strip().lower().rstrip(".,!")
    return lowered in APPROVAL_WORDS or any(w in lowered for w in APPROVAL_WORDS)


def should_activate_step_driver() -> bool:
    """True if plan mode is on and last assistant message has parseable steps."""
    if not (state.ui.plan_mode or state.ui.plan_mode_this_turn):
        return False
    if state.ui.plan_executing:
        return False  # already running
    for msg in reversed(state.session.messages):
        if msg["role"] == "assistant":
            return bool(parse_plan_steps(msg.get("content", "")))
    return False


def build_step_prompt(index: int, steps: list[str], goal: str = "") -> str:
    total = len(steps)
    step_text = steps[index]
    goal_line = f" Original goal: {goal}." if goal else ""
    return (
        f"[Step {index + 1}/{total} of {total}]{goal_line} "
        f"Execute ONLY this step and stop: {step_text}. "
        f"Do not proceed to any further steps. When done, confirm what you did."
    )
