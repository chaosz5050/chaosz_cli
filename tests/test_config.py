"""
Tests for config.py — memory tag processing and system prompt building.
State attributes are patched on the correct domain sub-objects (state.reasoning,
state.workspace) to match the refactored AppState structure.
Filesystem writes are redirected to tmp_path so real config files are never touched.
"""

import json
from unittest.mock import patch

import pytest

from chaosz import config as cfg
from chaosz.state import state


# ---------------------------------------------------------------------------
# process_memory_tags
# ---------------------------------------------------------------------------

def test_process_memory_tags_strips_tag_from_output(tmp_path):
    memory_file = tmp_path / "memory.json"

    with (
        patch.object(cfg, "MEMORY_FILE", str(memory_file)),
        patch.object(state.reasoning, "memory", {cat: [] for cat in cfg.VALID_CATEGORIES}),
    ):
        result = cfg.process_memory_tags(
            "Hello! [REMEMBER: preferences: dark mode] Hope that helps."
        )

    assert "[REMEMBER:" not in result
    assert "Hello!" in result
    assert "Hope that helps." in result


def test_process_memory_tags_persists_valid_category(tmp_path):
    memory_file = tmp_path / "memory.json"
    mem = {cat: [] for cat in cfg.VALID_CATEGORIES}

    with (
        patch.object(cfg, "MEMORY_FILE", str(memory_file)),
        patch.object(state.reasoning, "memory", mem),
    ):
        cfg.process_memory_tags("[REMEMBER: preferences: use fish shell]")

    assert "use fish shell" in mem["preferences"]


def test_process_memory_tags_ignores_invalid_category(tmp_path):
    memory_file = tmp_path / "memory.json"
    mem = {cat: [] for cat in cfg.VALID_CATEGORIES}

    with (
        patch.object(cfg, "MEMORY_FILE", str(memory_file)),
        patch.object(state.reasoning, "memory", mem),
    ):
        cfg.process_memory_tags("[REMEMBER: made_up_category: some text]")

    assert all(len(v) == 0 for v in mem.values())


def test_process_memory_tags_multiple_tags(tmp_path):
    memory_file = tmp_path / "memory.json"
    mem = {cat: [] for cat in cfg.VALID_CATEGORIES}

    with (
        patch.object(cfg, "MEMORY_FILE", str(memory_file)),
        patch.object(state.reasoning, "memory", mem),
    ):
        result = cfg.process_memory_tags(
            "[REMEMBER: about_user: name is René] "
            "[REMEMBER: preferences: concise answers]"
        )

    assert "name is René" in mem["about_user"]
    assert "concise answers" in mem["preferences"]
    assert "[REMEMBER:" not in result


# ---------------------------------------------------------------------------
# build_system_prompt
# ---------------------------------------------------------------------------

def test_build_system_prompt_includes_working_dir():
    with (
        patch.object(state.workspace, "working_dir", "/home/user/project"),
        patch.object(state.reasoning, "personality", ""),
        patch.object(state.reasoning, "memory", {cat: [] for cat in cfg.VALID_CATEGORIES}),
    ):
        prompt = cfg.build_system_prompt()

    assert "/home/user/project" in prompt


def test_build_system_prompt_includes_personality():
    with (
        patch.object(state.workspace, "working_dir", ""),
        patch.object(state.reasoning, "personality", "Be concise and direct."),
        patch.object(state.reasoning, "memory", {cat: [] for cat in cfg.VALID_CATEGORIES}),
    ):
        prompt = cfg.build_system_prompt()

    assert "Be concise and direct." in prompt
    assert "Communication Style" in prompt


def test_build_system_prompt_includes_memory():
    mem = {cat: [] for cat in cfg.VALID_CATEGORIES}
    mem["about_user"] = ["name is René"]

    with (
        patch.object(state.workspace, "working_dir", ""),
        patch.object(state.reasoning, "personality", ""),
        patch.object(state.reasoning, "memory", mem),
    ):
        prompt = cfg.build_system_prompt()

    assert "name is René" in prompt
