from pathlib import Path

from chaosz import config, skills
from chaosz.state import state
from chaosz.ui import app_rendering, routing


def _write_skill(root: Path, name: str, description: str, body: str = "Follow this workflow.") -> None:
    skill_dir = root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n",
        encoding="utf-8",
    )


def test_startup_creates_skills_directory_without_changing_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    skills_dir = Path(skills.get_skills_dir())

    skills.ensure_skills_dir()

    assert skills_dir.is_dir()
    _write_skill(tmp_path, "custom", "Custom workflow for an unusual task.")
    skills.ensure_skills_dir()

    assert skills.list_skills() == ["custom"]


def test_discovery_requires_standard_folder_and_matching_name(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "omarchy-linux", "Configure Omarchy and Hyprland.")
    _write_skill(tmp_path, "wrong-folder", "This metadata will be changed.")
    mismatch = tmp_path / "skills" / "wrong-folder" / "SKILL.md"
    mismatch.write_text(mismatch.read_text(encoding="utf-8").replace("name: wrong-folder", "name: different"), encoding="utf-8")
    (tmp_path / "skills" / "legacy.md").write_text("legacy", encoding="utf-8")

    assert skills.list_skills() == ["omarchy-linux"]
    assert "Configure Omarchy" in skills.load_skill("omarchy-linux")
    assert skills.load_skill("wrong-folder") == ""


def test_router_selects_confident_metadata_match_and_ignores_weak_match(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "omarchy-linux", "Configure Omarchy, Hyprland, Waybar, and Hyprlock safely.")
    _write_skill(tmp_path, "mcp-builder", "Build FastMCP and Model Context Protocol servers and tools.")
    _write_skill(tmp_path, "coder", "Implement, fix, refactor, debug, and test source code applications.")

    assert skills.find_matching_skill("Add a Hyprland window rule").name == "omarchy-linux"
    assert skills.find_matching_skill("Build a FastMCP server").name == "mcp-builder"
    assert skills.find_matching_skill("Please fix this Python bug").name == "coder"
    assert skills.find_matching_skill("Can you help me today?") is None


def test_router_selects_two_independent_high_confidence_skills(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "coder", "Implement, build, or fix coding software applications.")
    _write_skill(tmp_path, "python-pyside", "Build Python PySide6 desktop GUI and Qt applications.")
    _write_skill(tmp_path, "mcp-builder", "Build Python FastMCP and Model Context Protocol servers.")

    matches = skills.find_matching_skills("Implement a Python PySide6 desktop GUI application")

    assert [skill.name for skill in matches] == ["python-pyside", "coder"]


def test_manual_skill_overrides_transient_auto_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "omarchy-linux", "Configure Omarchy and Hyprland safely.")
    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skills
    try:
        state.reasoning.active_skill = "manual"
        state.reasoning.turn_skills = ["stale"]
        assert skills.select_turn_skills("Configure Omarchy") == []
        assert state.reasoning.turn_skills == []
        assert skills.get_effective_skill_name() == "manual"
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skills = previous_turn


def test_auto_skills_are_injected_into_the_system_prompt_in_ranked_order(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "python-pyside", "Build Python PySide6 desktop GUI applications.", "PYSIDE_SKILL_MARKER")
    _write_skill(tmp_path, "coder", "Implement coding applications.", "CODER_SKILL_MARKER")
    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skills
    previous_personality = state.reasoning.personality
    previous_workdir = state.workspace.working_dir
    previous_memory = state.reasoning.memory
    try:
        state.reasoning.active_skill = None
        state.reasoning.turn_skills = ["python-pyside", "coder"]
        state.reasoning.personality = ""
        state.workspace.working_dir = ""
        state.reasoning.memory = {category: [] for category in config.VALID_CATEGORIES}
        prompt = config.build_system_prompt()
        assert "Multiple task skills are active" in prompt
        assert prompt.index("PYSIDE_SKILL_MARKER") < prompt.index("CODER_SKILL_MARKER")
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skills = previous_turn
        state.reasoning.personality = previous_personality
        state.workspace.working_dir = previous_workdir
        state.reasoning.memory = previous_memory


def test_router_announces_selected_auto_skills_at_turn_start(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "coder", "Implement coding applications.")
    _write_skill(tmp_path, "python-pyside", "Build Python PySide6 desktop GUI applications.")

    class App:
        def __init__(self):
            self.lines = []
            self.footer_updates = 0

        def _write(self, _label, content):
            self.lines.append(content.plain)

        def _update_footer(self):
            self.footer_updates += 1

    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skills
    previous_plan_executing = state.ui.plan_executing
    previous_plan_mode = state.ui.plan_mode
    try:
        state.reasoning.active_skill = None
        state.reasoning.turn_skills = []
        state.ui.plan_executing = False
        state.ui.plan_mode = False
        app = App()
        monkeypatch.setattr(routing, "classify_request_route", lambda _prompt: "agent")
        monkeypatch.setattr(routing, "_route_registry", lambda: {"agent": lambda _app, _prompt: None})

        routing.run_routed_turn(app, "Implement a Python PySide6 desktop GUI application")

        assert app.lines == ["✦ Auto skills: python-pyside + coder"]
        assert app.footer_updates == 1
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skills = previous_turn
        state.ui.plan_executing = previous_plan_executing
        state.ui.plan_mode = previous_plan_mode


def test_footer_uses_a_compact_automatic_skill_count():
    class InfoBar:
        def __init__(self):
            self.value = ""

        def update(self, value):
            self.value = value

    class App:
        def __init__(self):
            self.info_bar = InfoBar()

        def query_one(self, selector, _widget_type):
            assert selector == "#info-bar"
            return self.info_bar

    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skills
    try:
        state.reasoning.active_skill = None
        state.reasoning.turn_skills = ["coder", "python-pyside"]
        app = App()

        app_rendering.update_footer(app)

        assert "✦ 2 skills" in app.info_bar.value
        assert "auto:coder" not in app.info_bar.value
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skills = previous_turn
