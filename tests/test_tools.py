from chaosz.state import state
from chaosz.tools import (
    build_file_read_session_grant,
    build_file_read_summary,
    is_file_read_allowed_by_session,
)


def test_file_read_grant_allows_same_file_different_range(tmp_path, monkeypatch):
    target = tmp_path / "main.py"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))

    grant = build_file_read_session_grant({"path": "main.py", "start_line": 0, "end_line": 1})

    assert grant is not None
    assert is_file_read_allowed_by_session(
        {"path": "main.py", "start_line": 1, "end_line": 3},
        {grant},
    ) is True


def test_file_read_grant_rejects_different_file(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "other.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))

    grant = build_file_read_session_grant({"path": "main.py"})

    assert grant is not None
    assert is_file_read_allowed_by_session({"path": "other.py"}, {grant}) is False


def test_file_read_grant_rejects_path_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))

    assert build_file_read_session_grant({"path": "../outside.py"}) is None


def test_file_read_summary_includes_line_range():
    assert build_file_read_summary(
        {"path": "main.py", "start_line": 10, "end_line": 20}
    ) == "read 'main.py' lines 10:20"
