from pathlib import Path

from chaosz import config, skills
from chaosz.state import state


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


def test_manual_skill_overrides_transient_auto_skill(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "omarchy-linux", "Configure Omarchy and Hyprland safely.")
    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skill
    try:
        state.reasoning.active_skill = "manual"
        state.reasoning.turn_skill = "stale"
        assert skills.select_turn_skill("Configure Omarchy") is None
        assert state.reasoning.turn_skill is None
        assert skills.get_effective_skill_name() == "manual"
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skill = previous_turn


def test_auto_skill_is_injected_into_the_system_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHAOSZ_DIR", str(tmp_path))
    _write_skill(tmp_path, "omarchy-linux", "Configure Omarchy and Hyprland safely.", "MANDATORY_SKILL_MARKER")
    previous_manual = state.reasoning.active_skill
    previous_turn = state.reasoning.turn_skill
    previous_personality = state.reasoning.personality
    previous_workdir = state.workspace.working_dir
    previous_memory = state.reasoning.memory
    try:
        state.reasoning.active_skill = None
        state.reasoning.turn_skill = "omarchy-linux"
        state.reasoning.personality = ""
        state.workspace.working_dir = ""
        state.reasoning.memory = {category: [] for category in config.VALID_CATEGORIES}
        prompt = config.build_system_prompt()
        assert "Task Mode — Active Skill (omarchy-linux)" in prompt
        assert "MANDATORY_SKILL_MARKER" in prompt
    finally:
        state.reasoning.active_skill = previous_manual
        state.reasoning.turn_skill = previous_turn
        state.reasoning.personality = previous_personality
        state.workspace.working_dir = previous_workdir
        state.reasoning.memory = previous_memory
