import os
import json
import re
import shutil

from chaosz.state import state

CHAOSZ_DIR   = os.path.expanduser("~/.config/chaosz")
CONFIG_FILE  = os.path.join(CHAOSZ_DIR, "config.json")
MEMORY_FILE  = os.path.join(CHAOSZ_DIR, "memory.json")
HISTORY_FILE = os.path.join(CHAOSZ_DIR, "history.json")
LOG_FILE     = os.path.join(CHAOSZ_DIR, "llm.log")
VALID_CATEGORIES = {"about_user", "preferences", "projects", "top_of_mind", "workspace_context"}


def _ensure_chaosz_dir() -> None:
    os.makedirs(CHAOSZ_DIR, exist_ok=True)
    os.chmod(CHAOSZ_DIR, 0o700)


_ensure_chaosz_dir()

DEFAULT_SYSTEM_PROMPT = """You are an intelligent, autonomous assistant operating globally on the user's machine. You can help with coding, writing, analysis, brainstorming, and anything else the user needs. You prefer clean, well-structured code.

You have access to file operation tools (file_read, file_write, file_edit, file_delete, file_rename). All file paths are resolved relative to the current working directory (the sandbox). Absolute paths are automatically re-rooted inside the sandbox — you cannot access files outside it. Use the shell_exec tool with `pwd` or `ls` to orient yourself if needed.

MANDATORY FILE TOOL RULE: When creating or modifying any file, you MUST call the file_write or file_edit tool. NEVER output file contents directly in the conversation. NEVER say "copy this code" or "paste this into a file". NEVER ask the user for approval in text — just call the tool. The permission system will automatically show the user a diff and ask for confirmation. Outputting code to chat instead of calling the tool is always wrong.

You have access to a shell_exec tool to run terminal commands on the user's CachyOS/Arch Linux system. Always use this tool when the user asks you to run, execute, check, install, or manage anything on their system. Always provide a clear reason for each command. Never chain destructive commands together in a single call — break them into separate tool calls so the user can approve each one individually.

You also have access to a web_search tool. Use it whenever the user asks about recent events, current news, live data, or requests a lookup — never claim to lack internet access when this tool is available.

## Memory System

You can persist information across sessions by including memory tags anywhere in your response. The tag is stripped from the displayed output — the user will not see it.

Syntax: [REMEMBER: category: text to remember]

Valid categories:
- about_user       — facts about the user (name, role, skills, preferences)
- preferences      — how the user likes things done (style, tools, workflow)
- projects         — ongoing projects, goals, context
- top_of_mind      — current tasks, priorities, things to follow up on
- workspace_context — codebase rules, architectural decisions, project conventions

Use memory tags proactively when you learn something worth remembering. Examples:
  [REMEMBER: about_user: prefers concise responses without trailing summaries]
  [REMEMBER: preferences: uses fish shell on CachyOS/Arch Linux]
  [REMEMBER: projects: building Chaosz CLI — a Python TUI using Textual]
  [REMEMBER: workspace_context: uses Textual for TUI components, prefer functional over OOP]
  [REMEMBER: top_of_mind: working on memory system and CHAOSZ.md feature]

You may include multiple tags in one response. Place them at the end of your message.

## Task Completion

When executing multi-step tasks, always complete each step in sequence before starting the next — do not reorder, skip, or batch steps.

After completing any agentic task that involved tool use (file writes, edits, deletes, renames, or shell commands), always end your response with a concise 1–2 sentence summary of what you did. Name the specific files changed and the action taken. Do not just say "done" or "finished". This rule applies even when the task was straightforward."""


def _read_config_file() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    try:
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_config_file(data: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)
    os.chmod(CONFIG_FILE, 0o600)


# ---------------------------------------------------------------------------
# Personality
# ---------------------------------------------------------------------------

def load_mcp_servers() -> dict:
    """Load MCP servers config dict from config.json.
    Returns {server_name: {transport, command, url, enabled, description}}.
    """
    return _read_config_file().get("mcp_servers", {})


def save_mcp_servers(servers: dict) -> None:
    """Persist MCP servers config dict to config.json."""
    data = _read_config_file()
    data["mcp_servers"] = servers
    _write_config_file(data)


def load_active_skill() -> str | None:
    """Load active skill name from config.json. Returns None if not set."""
    return _read_config_file().get("active_skill") or None


def save_active_skill(name: str | None) -> None:
    """Persist active skill name to config.json. Pass None to clear."""
    data = _read_config_file()
    if name:
        data["active_skill"] = name
    else:
        data.pop("active_skill", None)
    _write_config_file(data)


def load_reason_enabled() -> bool:
    """Load reason_enabled flag from project config.json."""
    return bool(_read_config_file().get("reason_enabled", False))


def save_reason_enabled(enabled: bool) -> None:
    """Persist reason_enabled flag to project config.json."""
    data = _read_config_file()
    data["reason_enabled"] = enabled
    _write_config_file(data)


def load_theme() -> str:
    """Load active theme name from config.json. Defaults to 'default'."""
    return _read_config_file().get("theme", "default")


def save_theme(name: str) -> None:
    """Persist active theme name to config.json."""
    data = _read_config_file()
    data["theme"] = name
    _write_config_file(data)


def load_show_header() -> bool:
    """Load show_header flag from config.json. Defaults to True."""
    return bool(_read_config_file().get("show_header", True))


def save_show_header(visible: bool) -> None:
    """Persist show_header flag to config.json."""
    data = _read_config_file()
    data["show_header"] = visible
    _write_config_file(data)


def load_personality() -> str:
    """Load personality string from project config.json."""
    return _read_config_file().get("personality", "")


def save_personality(personality: str) -> None:
    """Save personality string to project config.json."""
    data = _read_config_file()
    data["personality"] = personality
    _write_config_file(data)


# ---------------------------------------------------------------------------
# App config (working dir etc.)
# ---------------------------------------------------------------------------

def load_config():
    data = _read_config_file()
    return {
        "models": data.get("models", []),
        "active_model": data.get("active_model"),
    }

def save_config(config):
    data = _read_config_file()
    for key in ("models", "active_model"):
        if key in config:
            data[key] = config[key]
    _write_config_file(data)


# ---------------------------------------------------------------------------
# Input history
# ---------------------------------------------------------------------------

def load_input_history() -> list[str]:
    if not os.path.exists(HISTORY_FILE): return []
    with open(HISTORY_FILE, "r") as f:
        try:
            data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception: return []

def save_input_history(history: list[str]) -> None:
    with open(HISTORY_FILE, "w") as f: json.dump(history[-500:], f)


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def load_memory():
    if not os.path.exists(MEMORY_FILE): return {cat: [] for cat in VALID_CATEGORIES}
    with open(MEMORY_FILE, "r") as f:
        try:
            mem = json.load(f)
            for cat in VALID_CATEGORIES:
                if cat not in mem: mem[cat] = []
            return mem
        except Exception: return {cat: [] for cat in VALID_CATEGORIES}


def save_memory(memory: dict) -> None:
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def add_memory(cat, text):
    if cat not in VALID_CATEGORIES or text in state.reasoning.memory[cat]: return
    state.reasoning.memory[cat].append(text)
    save_memory(state.reasoning.memory)

def _load_chaosz_md() -> str:
    """Load chaosz.md from the current working directory if present."""
    if not state.workspace.working_dir:
        return ""
    md_path = os.path.join(state.workspace.working_dir, "chaosz.md")
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def build_system_prompt():
    from datetime import datetime
    parts = [DEFAULT_SYSTEM_PROMPT]
    parts.append(f"\nCURRENT DATE: {datetime.now().strftime('%A, %B %d, %Y')}")
    if state.workspace.working_dir:
        parts.append(f"\nCURRENT_WORKING_DIRECTORY: {state.workspace.working_dir}")
    if state.reasoning.personality:
        parts.append(
            "\nCommunication Style (Personality):\n"
            "The following instructions govern HOW you communicate — your tone, "
            "persona, language, verbosity, and manner of address. Apply these "
            "style rules to every response regardless of what task you are doing.\n"
            + state.reasoning.personality
        )
    if state.reasoning.active_skill:
        from chaosz.skills import load_skill
        skill_content = load_skill(state.reasoning.active_skill)
        if skill_content:
            if state.reasoning.personality:
                parts.append(
                    "\nNote: Both a communication style and a task skill are active. "
                    "Let the skill govern task behavior (WHAT you do, how you structure your work). "
                    "Let the personality govern tone (HOW you write and speak). "
                    "Where they appear to conflict, the skill takes precedence for task behavior."
                )
            parts.append(
                f"\nTask Mode — Active Skill ({state.reasoning.active_skill}):\n"
                "The following instructions govern WHAT you do and HOW you approach this "
                "type of task — methodology, workflow, conventions, and deliverable format. "
                "Follow these task instructions precisely.\n"
                + skill_content
            )
    chaosz_md = _load_chaosz_md()
    if chaosz_md:
        parts.append("\nProject Context (chaosz.md):\n" + chaosz_md)
    mem_parts = []
    for cat in sorted(VALID_CATEGORIES):
        if state.reasoning.memory.get(cat):
            mem_parts.append(f"- {cat.replace('_', ' ').title()}:")
            for item in state.reasoning.memory[cat]: mem_parts.append(f"  * {item}")
    if mem_parts: parts.append("\nMemory Context:\n" + "\n".join(mem_parts))
    from chaosz.mcp_manager import get_all_mcp_prompts
    for prompt_text in get_all_mcp_prompts():
        if prompt_text:
            parts.append("\n" + prompt_text)
    if state.ui.plan_summarizing:
        parts.append(
            "\nAll plan steps have been executed. Write a concise summary of everything you "
            "accomplished. Do not call any tools. Do not present a new plan."
        )
    elif state.ui.plan_mode or state.ui.plan_mode_this_turn:
        parts.append(
            "\nPLANNING MODE ACTIVE: Before calling any file operation or shell tools, you MUST "
            "first present a numbered plan of exactly what you intend to do. Format each step as a "
            "simple numbered list: '1. Step one', '2. Step two', etc. After presenting the plan, "
            "STOP — do NOT ask for confirmation in text, and do NOT call any tools. "
            "The interface will show an approval menu. Execution begins automatically once approved."
        )
    if state.ui.plan_executing and state.ui.plan_steps:
        idx = state.ui.plan_step_index
        total = len(state.ui.plan_steps)
        step_text = state.ui.plan_steps[idx]
        parts.append(
            f"\nSTEP EXECUTION MODE (step {idx + 1}/{total}): You are executing ONE step only: "
            f'"{step_text}". Complete it using the appropriate tools, then stop. '
            f"Do not execute any other steps. Do not ask for further confirmation."
        )
    return "\n".join(parts)


def process_memory_tags(text: str) -> str:
    """Strip [REMEMBER:] tags from text, persisting each valid one to memory.
    Returns the display-safe text with all tags removed.
    Called by all three route handlers so memory updates work on every turn.
    """
    for cat, content in re.findall(r"\[REMEMBER:\s*(\w+):\s*(.*?)\]", text, re.DOTALL):
        cat = cat.strip()
        content = content.strip()
        if cat in VALID_CATEGORIES and content:
            add_memory(cat, content)
    return re.sub(r"\[REMEMBER:\s*\w+:\s*.*?\]", "", text, flags=re.DOTALL)
