"""
Tests for plan_driver.py — all pure functions, no mocking required.
"""

import pytest

from chaosz.plan_driver import (
    build_step_prompt,
    build_step_retry_prompt,
    is_plan_approval,
    is_plan_generation_phase,
    parse_plan_steps,
)
from chaosz.state import state


# ---------------------------------------------------------------------------
# parse_plan_steps
# ---------------------------------------------------------------------------

def test_parse_plan_steps_dot_separator():
    text = "1. Install dependencies\n2. Run migrations\n3. Deploy"
    assert parse_plan_steps(text) == ["Install dependencies", "Run migrations", "Deploy"]


def test_parse_plan_steps_paren_separator():
    text = "1) First step\n2) Second step"
    assert parse_plan_steps(text) == ["First step", "Second step"]


def test_parse_plan_steps_empty_string():
    assert parse_plan_steps("") == []


def test_parse_plan_steps_no_numbered_list():
    assert parse_plan_steps("Just some prose without any numbered steps.") == []


def test_parse_plan_steps_ignores_inline_numbers():
    text = "There are 3 options.\n1. First\n2. Second"
    assert parse_plan_steps(text) == ["First", "Second"]


# ---------------------------------------------------------------------------
# is_plan_approval
# ---------------------------------------------------------------------------

def test_is_plan_approval_exact_match():
    assert is_plan_approval("yes") is True


def test_is_plan_approval_case_insensitive():
    assert is_plan_approval("GO") is True
    assert is_plan_approval("Ok") is True


def test_is_plan_approval_strips_punctuation():
    assert is_plan_approval("yes!") is True
    assert is_plan_approval("ok.") is True


def test_is_plan_approval_partial_phrase():
    assert is_plan_approval("go ahead") is True
    assert is_plan_approval("sounds good to me") is True


def test_is_plan_approval_rejects_non_approval():
    assert is_plan_approval("no") is False
    assert is_plan_approval("wait") is False
    assert is_plan_approval("let me think") is False


# ---------------------------------------------------------------------------
# build_step_prompt
# ---------------------------------------------------------------------------

def test_build_step_prompt_numbering():
    steps = ["alpha", "beta", "gamma"]
    assert "Step 1/3" in build_step_prompt(0, steps)
    assert "Step 2/3" in build_step_prompt(1, steps)
    assert "Step 3/3" in build_step_prompt(2, steps)


def test_build_step_prompt_contains_step_text():
    steps = ["run the tests", "deploy the app"]
    assert "run the tests" in build_step_prompt(0, steps)
    assert "deploy the app" in build_step_prompt(1, steps)


def test_build_step_prompt_with_goal():
    steps = ["write the code"]
    prompt = build_step_prompt(0, steps, goal="add dark mode to the UI")
    assert "add dark mode to the UI" in prompt
    assert "Original goal" in prompt


def test_build_step_prompt_without_goal():
    steps = ["write the code"]
    prompt = build_step_prompt(0, steps)
    assert "Original goal" not in prompt


def test_build_step_prompt_includes_stop_instruction():
    steps = ["do something"]
    prompt = build_step_prompt(0, steps)
    assert "Do not proceed" in prompt


def test_step_retry_prompt_keeps_the_same_step_and_requires_verification():
    prompt = build_step_retry_prompt(1, ["inspect", "fix the GUI", "deploy"], goal="repair app")
    assert "Step 2/3 retry" in prompt
    assert "fix the GUI" in prompt
    assert "Do not repeat a failed command unchanged" in prompt
    assert "verification" in prompt


def test_plan_generation_phase_only_before_execution_or_summary():
    old = (
        state.ui.plan_mode,
        state.ui.plan_mode_this_turn,
        state.ui.plan_executing,
        state.ui.plan_summarizing,
    )
    try:
        state.ui.plan_mode = True
        state.ui.plan_mode_this_turn = False
        state.ui.plan_executing = False
        state.ui.plan_summarizing = False
        assert is_plan_generation_phase() is True

        state.ui.plan_executing = True
        assert is_plan_generation_phase() is False

        state.ui.plan_executing = False
        state.ui.plan_summarizing = True
        assert is_plan_generation_phase() is False
    finally:
        (
            state.ui.plan_mode,
            state.ui.plan_mode_this_turn,
            state.ui.plan_executing,
            state.ui.plan_summarizing,
        ) = old
