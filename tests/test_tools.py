import os

from chaosz.state import state
from chaosz.tools import (
    build_file_read_session_grant,
    build_file_read_summary,
    is_file_read_allowed_by_session,
    resolve_safe_path,
)


# ---------------------------------------------------------------------------
# resolve_safe_path: absolute paths inside the sandbox must NOT be re-rooted
# (regression: writing /home/.../proj/x.html when working_dir is /home/.../proj
#  used to produce a doubled phantom path /home/.../proj/home/.../proj/x.html)
# ---------------------------------------------------------------------------

def test_resolve_absolute_path_inside_sandbox_maps_to_real_file(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))
    abs_target = str(tmp_path / "sub" / "index.html")

    resolved, err = resolve_safe_path(abs_target)

    assert err is None
    # Must resolve to the file itself, not a re-rooted duplicate underneath base.
    assert resolved == os.path.realpath(abs_target)
    assert "home" not in os.path.relpath(resolved, str(tmp_path)).split(os.sep)


def test_resolve_relative_path_resolves_under_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path))

    resolved, err = resolve_safe_path("sub/index.html")

    assert err is None
    assert resolved == os.path.realpath(str(tmp_path / "sub" / "index.html"))


def test_resolve_absolute_path_outside_sandbox_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(state.workspace, "working_dir", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir()

    resolved, err = resolve_safe_path(str(tmp_path / "elsewhere" / "secret.txt"))

    assert resolved is None
    assert err is not None and "outside sandbox" in err


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
