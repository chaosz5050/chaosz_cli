"""
Tests for shell.py — pure helper functions, no I/O required.
"""

import pytest

from chaosz.shell import is_always_prompt_command, is_command_allowed_by_session


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


def test_is_command_allowed_by_session_readonly_base_in_set():
    # "ls" base command is in the allowed set → full invocation allowed
    assert is_command_allowed_by_session("ls -la /tmp", {"ls"}) is True


def test_is_command_allowed_by_session_readonly_base_not_in_set():
    assert is_command_allowed_by_session("ls -la /tmp", set()) is False


def test_is_command_allowed_by_session_readonly_with_dangerous_op_rejected():
    # Pipe makes even a whitelisted read-only command unsafe
    assert is_command_allowed_by_session("ls | rm -rf /", {"ls"}) is False


def test_is_command_allowed_by_session_redirect_rejected():
    assert is_command_allowed_by_session("cat file > /etc/passwd", {"cat"}) is False


def test_is_command_allowed_by_session_non_readonly_base_not_whitelisted():
    # "pip" is not in READ_ONLY_CMDS, so base-command matching doesn't apply
    assert is_command_allowed_by_session("pip install requests", {"pip"}) is False


def test_is_command_allowed_by_session_empty_command():
    assert is_command_allowed_by_session("", {"ls"}) is False
