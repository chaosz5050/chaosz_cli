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


def is_plan_generation_phase() -> bool:
    """True while the model is drafting a plan that has not been approved.

    This deliberately excludes the step driver and the final summary turn.  The
    caller uses it as a capability boundary: plan drafting receives no tools,
    so approval cannot arrive after a model has already changed the workspace.
    """
    return bool(
        (state.ui.plan_mode or state.ui.plan_mode_this_turn)
        and not state.ui.plan_executing
        and not state.ui.plan_summarizing
    )


def build_step_prompt(index: int, steps: list[str], goal: str = "") -> str:
    total = len(steps)
    step_text = steps[index]
    goal_line = f" Original goal: {goal}." if goal else ""
    return (
        f"[Step {index + 1}/{total} of {total}]{goal_line} "
        f"Execute ONLY this step and stop: {step_text}. "
        f"Do not proceed to any further steps. When done, confirm what you did."
    )


def build_step_retry_prompt(index: int, steps: list[str], goal: str = "") -> str:
    """Ask for one focused recovery attempt without advancing the plan."""
    total = len(steps)
    step_text = steps[index]
    goal_line = f" Original goal: {goal}." if goal else ""
    return (
        f"[Step {index + 1}/{total} retry]{goal_line} The previous attempt did not complete: "
        "there was a failed tool action, missing final response, or required verification did not pass. "
        "Review the most recent tool result, fix the reported problem, and execute ONLY this step: "
        f"{step_text}. Do not repeat a failed command unchanged. If source code changed, run a focused "
        "verification that actually passes before stopping."
    )
