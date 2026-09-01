"""Discover, load, and route Agent Skills stored below the Chaosz config directory."""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shutil


SKILL_FILE = "SKILL.md"
_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.-]*")
_ROUTING_STOPWORDS = {
    "about", "after", "agent", "and", "are", "build", "can", "code", "configure",
    "does", "for", "from", "help", "into", "local", "model", "models", "on", "or",
    "skill", "skills", "task", "that", "the", "this", "to", "use", "when", "with",
    "work", "working", "workflow", "your",
}


@dataclass(frozen=True)
class Skill:
    """A discovered Agent Skill and its lightweight routing metadata."""

    name: str
    description: str
    path: str


def get_skills_dir() -> str:
    """Return the global Agent Skills directory under ~/.config/chaosz/skills."""
    from chaosz.config import CHAOSZ_DIR

    return os.path.join(CHAOSZ_DIR, "skills")


def ensure_skills_dir() -> None:
    """Create the user skills directory without changing installed skills."""
    os.makedirs(get_skills_dir(), exist_ok=True)


def _parse_frontmatter(path: str) -> tuple[str, str] | None:
    """Read the required small YAML subset without adding a runtime dependency."""
    try:
        with open(path, encoding="utf-8") as skill_file:
            text = skill_file.read()
    except OSError:
        return None

    if not text.startswith("---\n"):
        return None
    try:
        header, _body = text[4:].split("\n---", 1)
    except ValueError:
        return None

    fields: dict[str, str] = {}
    current_key: str | None = None
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() and current_key:
            fields[current_key] = f"{fields[current_key]} {line.strip()}".strip()
            continue
        match = re.match(r"^([a-zA-Z][\w-]*):\s*(.*)$", line)
        if not match:
            current_key = None
            continue
        key, value = match.groups()
        current_key = key
        fields[key] = value.strip().strip('"\'')

    name = fields.get("name", "")
    description = fields.get("description", "")
    if description in {"|", ">", ">-", "|-"}:
        description = ""
    if not _NAME_RE.fullmatch(name) or not description:
        return None
    return name, description


def discover_skills() -> list[Skill]:
    """Return valid folder-based Agent Skills, sorted by their stable name."""
    skills_dir = get_skills_dir()
    try:
        entries = sorted(os.scandir(skills_dir), key=lambda entry: entry.name)
    except OSError:
        return []

    discovered: list[Skill] = []
    for entry in entries:
        if not entry.is_dir():
            continue
        metadata = _parse_frontmatter(os.path.join(entry.path, SKILL_FILE))
        if metadata is None:
            continue
        name, description = metadata
        if name != entry.name:
            continue
        discovered.append(Skill(name, description, os.path.join(entry.path, SKILL_FILE)))
    return discovered


def list_skills() -> list[str]:
    """Return sorted names for all valid installed Agent Skills."""
    return [skill.name for skill in discover_skills()]


def get_skill_path(name: str) -> str | None:
    """Return a valid skill's instruction file path, if it exists."""
    safe_name = os.path.basename(name)
    for skill in discover_skills():
        if skill.name == safe_name:
            return skill.path
    return None


def load_skill(name: str) -> str:
    """Read one validated Agent Skill. Returns empty text when unavailable."""
    path = get_skill_path(name)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as skill_file:
            return skill_file.read().strip()
    except OSError:
        return ""


def save_skill(name: str, content: str) -> None:
    """Create or replace a user-authored Agent Skill from the /skill UI."""
    safe_name = os.path.basename(name)
    if not _NAME_RE.fullmatch(safe_name):
        raise ValueError("Skill names must use lowercase letters, numbers, and hyphens.")
    skill_dir = os.path.join(get_skills_dir(), safe_name)
    os.makedirs(skill_dir, exist_ok=True)
    path = os.path.join(skill_dir, SKILL_FILE)
    body = content.strip()
    with open(path, "w", encoding="utf-8") as skill_file:
        skill_file.write(
            f"---\nname: {safe_name}\n"
            f"description: Custom {safe_name} workflow.\n---\n\n{body}\n"
        )


def delete_skill(name: str) -> bool:
    """Delete one validated skill directory. Returns False when it is missing."""
    path = get_skill_path(name)
    if not path:
        return False
    try:
        shutil.rmtree(os.path.dirname(path))
        return True
    except OSError:
        return False


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def find_matching_skills(user_input: str, max_skills: int = 2) -> list[Skill]:
    """Return up to ``max_skills`` high-confidence deterministic matches."""
    if max_skills <= 0:
        return []
    text = (user_input or "").lower()
    prompt_tokens = _tokens(text)
    if not prompt_tokens:
        return []

    skills = discover_skills()
    description_token_sets = {
        skill.name: {
            token for token in _tokens(skill.description)
            if token not in _ROUTING_STOPWORDS and len(token) >= 3
        }
        for skill in skills
    }
    token_frequency = {
        token: sum(token in tokens for tokens in description_token_sets.values())
        for tokens in description_token_sets.values()
        for token in tokens
    }

    candidates: list[tuple[int, int, bool, Skill]] = []
    for skill in skills:
        name_phrase = skill.name.replace("-", " ")
        name_tokens = _tokens(skill.name.replace("-", " "))
        description_tokens = description_token_sets[skill.name]
        matched_name = name_tokens & prompt_tokens
        matched_description = description_tokens & prompt_tokens
        score = len(matched_description) + (2 * len(matched_name))
        strong_match = skill.name in text or name_phrase in text
        strong_match = strong_match or any(
            token_frequency[token] == 1 and len(token) >= 3
            for token in matched_description
        )
        if strong_match:
            score += 6
        candidates.append((score, len(matched_name | matched_description), strong_match, skill))

    eligible = [
        candidate
        for candidate in candidates
        if candidate[0] > 0 and (candidate[2] or candidate[1] >= 2)
    ]
    eligible.sort(key=lambda item: (-item[0], -item[1], item[3].name))
    return [candidate[3] for candidate in eligible[:max_skills]]


def find_matching_skill(user_input: str) -> Skill | None:
    """Return the highest-ranked automatic match for compatibility callers."""
    matches = find_matching_skills(user_input, max_skills=1)
    return matches[0] if matches else None


def select_turn_skills(user_input: str) -> list[Skill]:
    """Set transient automatic skills unless a persistent manual skill is active."""
    from chaosz.state import state

    state.reasoning.turn_skills = []
    if state.reasoning.active_skill:
        return []
    matches = find_matching_skills(user_input)
    state.reasoning.turn_skills = [skill.name for skill in matches]
    return matches


def select_turn_skill(user_input: str) -> Skill | None:
    """Return the first selected skill for compatibility callers."""
    matches = select_turn_skills(user_input)
    return matches[0] if matches else None


def clear_turn_skills() -> None:
    """Clear automatic skills once their task has reached a terminal state."""
    from chaosz.state import state

    state.reasoning.turn_skills = []


def get_effective_skill_names() -> list[str]:
    """Return the manual override or this turn's automatic skills in order."""
    from chaosz.state import state

    if state.reasoning.active_skill:
        return [state.reasoning.active_skill]
    return list(state.reasoning.turn_skills)


def get_effective_skill_name() -> str | None:
    """Return the first effective skill for compatibility callers."""
    names = get_effective_skill_names()
    return names[0] if names else None
