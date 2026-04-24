"""
Tests for restore_session() in session.py.

Each test writes a fake session_001.json to tmp_path and patches LIVE_SESSION
so the real config directory is never touched.
"""

import json
from unittest.mock import patch

import pytest

import chaosz.session as sess
from chaosz.state import state


def _write_session(path, messages):
    path.write_text(json.dumps({"messages": messages}))


# ---------------------------------------------------------------------------
# Normal message types
# ---------------------------------------------------------------------------

def test_restore_passes_through_regular_messages(tmp_path):
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ])

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    assert state.session.messages == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_restore_maps_reflection_summary_to_user_assistant_pair(tmp_path):
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [
        {"role": "reflection_summary", "content": "Working on auth module."},
    ])

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    assert len(state.session.messages) == 2
    assert state.session.messages[0]["role"] == "user"
    assert "[REFLECTION SUMMARY]" in state.session.messages[0]["content"]
    assert "Working on auth module." in state.session.messages[0]["content"]
    assert state.session.messages[1]["role"] == "assistant"


# ---------------------------------------------------------------------------
# Tool-call stripping (regression tests for the bug fix)
# ---------------------------------------------------------------------------

def test_restore_strips_tool_calls_keeps_content(tmp_path):
    """Assistant message with tool_calls AND content → content kept, tool_calls gone."""
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [
        {
            "role": "assistant",
            "content": "Let me read that file.",
            "tool_calls": [{"id": "tc_1", "function": {"name": "file_read", "arguments": "{}"}}],
        },
    ])

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    assert len(state.session.messages) == 1
    msg = state.session.messages[0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Let me read that file."
    assert "tool_calls" not in msg


def test_restore_skips_tool_only_assistant_turn(tmp_path):
    """Assistant message with tool_calls but NO content → skipped entirely."""
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"id": "tc_2", "function": {"name": "shell_exec", "arguments": "{}"}}],
        },
    ])

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    assert state.session.messages == []


def test_restore_skips_tool_role_messages(tmp_path):
    """role == 'tool' messages are always dropped."""
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [
        {"role": "user", "content": "do something"},
        {"role": "tool", "tool_call_id": "tc_3", "content": "result"},
    ])

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    roles = [m["role"] for m in state.session.messages]
    assert "tool" not in roles
    assert roles == ["user"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_restore_empty_messages_leaves_state_unchanged(tmp_path):
    session_file = tmp_path / "session_001.json"
    _write_session(session_file, [])
    state.session.messages = [{"role": "user", "content": "prior"}]

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    # empty messages list → function returns early, state untouched
    assert state.session.messages == [{"role": "user", "content": "prior"}]


def test_restore_missing_file_does_not_crash(tmp_path):
    missing = str(tmp_path / "nonexistent.json")
    state.session.messages = []

    with patch.object(sess, "LIVE_SESSION", missing):
        sess.restore_session()

    assert state.session.messages == []


def test_restore_malformed_json_does_not_crash(tmp_path):
    session_file = tmp_path / "session_001.json"
    session_file.write_text("not valid json {{{")
    state.session.messages = []

    with patch.object(sess, "LIVE_SESSION", str(session_file)):
        sess.restore_session()

    assert state.session.messages == []
