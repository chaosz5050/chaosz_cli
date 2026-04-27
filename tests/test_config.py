"""
Tests for config.py — memory tag processing and system prompt building.
State attributes are patched on the correct domain sub-objects (state.reasoning,
state.workspace) to match the refactored AppState structure.
Filesystem writes are redirected to tmp_path so real config files are never touched.
"""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from chaosz import config as cfg
from chaosz.state import state


# ---------------------------------------------------------------------------
# Import and write-time filesystem behavior
# ---------------------------------------------------------------------------

def test_import_config_does_not_create_chaosz_dir(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; "
                "import chaosz.config; "
                "print(os.path.exists(os.path.join(os.environ['HOME'], '.config', 'chaosz')))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.stdout.strip() == "False"


def test_write_config_file_creates_config_dir(tmp_path):
    chaosz_dir = tmp_path / "chaosz"
    config_file = chaosz_dir / "config.json"

    with (
        patch.object(cfg, "CHAOSZ_DIR", str(chaosz_dir)),
        patch.object(cfg, "CONFIG_FILE", str(config_file)),
    ):
        cfg._write_config_file({"theme": "default"})

    assert config_file.exists()
    assert json.loads(config_file.read_text()) == {"theme": "default"}


def test_save_input_history_creates_config_dir(tmp_path):
    chaosz_dir = tmp_path / "chaosz"
    history_file = chaosz_dir / "history.json"

    with (
        patch.object(cfg, "CHAOSZ_DIR", str(chaosz_dir)),
        patch.object(cfg, "HISTORY_FILE", str(history_file)),
    ):
        cfg.save_input_history(["hello"])

    assert json.loads(history_file.read_text()) == ["hello"]


def test_save_memory_creates_config_dir(tmp_path):
    chaosz_dir = tmp_path / "chaosz"
    memory_file = chaosz_dir / "memory.json"
    memory = {cat: [] for cat in cfg.VALID_CATEGORIES}
    memory["preferences"] = ["concise"]

    with (
        patch.object(cfg, "CHAOSZ_DIR", str(chaosz_dir)),
        patch.object(cfg, "MEMORY_FILE", str(memory_file)),
    ):
        cfg.save_memory(memory)

    assert json.loads(memory_file.read_text())["preferences"] == ["concise"]


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
            "[REMEMBER: about_user: name is Alice] "
            "[REMEMBER: preferences: concise answers]"
        )

    assert "name is Alice" in mem["about_user"]
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
    mem["about_user"] = ["name is Alice"]

    with (
        patch.object(state.workspace, "working_dir", ""),
        patch.object(state.reasoning, "personality", ""),
        patch.object(state.reasoning, "memory", mem),
    ):
        prompt = cfg.build_system_prompt()

    assert "name is Alice" in prompt
