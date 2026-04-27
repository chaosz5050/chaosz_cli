"""
Tests for shell.py — pure helper functions, no I/O required.
"""

import pytest

from chaosz.shell import build_shell_session_grants, is_always_prompt_command, is_command_allowed_by_session
from chaosz.state import state


# ---------------------------------------------------------------------------
# is_always_prompt_command
# ---------------------------------------------------------------------------

def test_is_always_prompt_command_bare_rm():
    assert is_always_prompt_command("rm") is True


def test_is_always_prompt_command_rm_with_flags():
    assert is_always_prompt_command("rm -rf /tmp/foo") is True


def test_is_always_prompt_command_absolute_path_rm():
    assert is_always_prompt_command("/bin/rm something") is True


def test_is_always_prompt_command_safe_command():
    assert is_always_prompt_command("ls -la") is False


def test_is_always_prompt_command_rm_as_argument_not_command():
    # "rm" appears only as an argument, not the command token
    assert is_always_prompt_command("echo rm") is False


def test_is_always_prompt_command_multiword_pacman_dangerous():
    assert is_always_prompt_command("pacman -S vim") is True
    assert is_always_prompt_command("pacman -R vim") is True


def test_is_always_prompt_command_pacman_safe_subcommand():
    # pacman -Q (query) is not in ALWAYS_PROMPT_COMMANDS
    assert is_always_prompt_command("pacman -Q vim") is False


def test_is_always_prompt_command_chained_dangerous():
    # rm appears after && — should still be caught
    assert is_always_prompt_command("ls && rm -rf /tmp") is True


# ---------------------------------------------------------------------------
# is_command_allowed_by_session
# ---------------------------------------------------------------------------

def test_is_command_allowed_by_session_exact_match():
    assert is_command_allowed_by_session("git status", {"git status"}) is True


def test_is_command_allowed_by_session_not_in_set():
    assert is_command_allowed_by_session("git status", set()) is False


def test_is_command_allowed_by_session_readonly_base_in_set_no_longer_broad():
    assert is_command_allowed_by_session("ls -la /tmp", {"ls"}) is False


def test_is_command_allowed_by_session_readonly_base_not_in_set():
    assert is_command_allowed_by_session("ls -la /tmp", set()) is False


def test_is_command_allowed_by_session_readonly_with_dangerous_op_rejected():
    assert is_command_allowed_by_session("ls | rm -rf /", {"ls"}) is False


def test_is_command_allowed_by_session_redirect_rejected():
    assert is_command_allowed_by_session("cat file > /etc/passwd", {"cat"}) is False


def test_is_command_allowed_by_session_non_readonly_base_not_whitelisted():
    assert is_command_allowed_by_session("pip install requests", {"pip"}) is False


def test_is_command_allowed_by_session_empty_command():
    assert is_command_allowed_by_session("", {"ls"}) is False


def test_pattern_grant_allows_same_directory_glob_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))
    grants = build_shell_session_grants("ls re*")

    assert is_command_allowed_by_session("ls ri*", grants) is True


def test_pattern_grant_rejects_pipe_even_when_shape_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))
    grants = build_shell_session_grants("ls re*")

    assert is_command_allowed_by_session("ls ri* | wc -l", grants) is False


def test_pattern_grant_rejects_path_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))
    grants = build_shell_session_grants("cat *.py")

    assert is_command_allowed_by_session("cat /tmp/*.py", grants) is False


def test_pattern_grant_does_not_apply_to_find(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))
    grants = build_shell_session_grants("find src*")

    assert "find src*" in grants
    assert is_command_allowed_by_session("find lib*", grants) is False
