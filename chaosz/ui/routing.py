"""
Routing module for Chaosz CLI.

Determines whether a user request should be handled by:
- 'investigation': Research and codebase analysis.
- 'compose': Text generation, summaries, or prompts.
- 'agent': File operations, shell commands, or general chat.

The scoring system uses a weighted heuristic based on keywords and phrases:
- Phrase matches (e.g., 'review this codebase') get a +3 boost as they are high-signal.
- Keyword matches (e.g., 'debug', 'readme') get a +1 boost.
- Specific combinations (e.g., 'debug' + 'why') get a +2 boost.
- A +2 margin is required to favor 'investigation' over other routes to prevent
  false positives for simple chat questions about the codebase.
"""

from __future__ import annotations

import re
from typing import Callable

from chaosz.state import state

RouteHandler = Callable[[object, str], None]

_INVESTIGATION_HINTS = [
    "review this codebase",
    "analyze the codebase",
    "analyse the codebase",
    "analyze the project structure",
    "analyse the project structure",
    "look through the code",
    "evaluate code quality",
    "explain how this app handles",
    "explain how this project handles",
    "debug why",
    "why this behavior",
    "why this behaviour",
    "explain how this code works",
    "explain how the code works",
    "explain how this app works",
    "explain how this module works",
    "review architecture",
    "analyze architecture",
    "analyse architecture",
]

_INVESTIGATION_KEYWORDS = {
    "review",
    "analyze",
    "analyse",
    "analysis",
    "codebase",
    "structure",
    "architecture",
    "debug",
    "investigate",
    "quality",
    "module",
    "bug",
}

_AGENT_KEYWORDS = {
    "edit",
    "change",
    "changes",
    "create",
    "file",
    "function",
    "path",
    "code",
    "rename",
    "delete",
    "write",
    "install",
    "run",
    "execute",
    "fix",
    "implement",
    "refactor",
    "update",
    "modify",
    "add",
}

_COMPOSE_HINTS = [
    "write a readme",
    "write readme",
    "generate a readme",
    "generate readme",
    "summarize this",
    "summarise this",
    "summarize this clearly",
    "summarise this clearly",
    "release notes",
    "write docs",
    "write documentation",
    "rewrite this",
    "rewrite this explanation",
    "draft a changelog",
    "improve this text",
    "improve wording",
    "improve this wording",
    "rephrase this",
    "reword this",
    "generate a prompt",
    "write a prompt",
    "create a prompt",
    "generate prompt",
    "project overview",
    "create text",
    "generate text",
]

_COMPOSE_KEYWORDS = {
    "write",
    "generate",
    "rewrite",
    "summarize",
    "summarise",
    "summary",
    "condense",
    "condensed",
    "rephrase",
    "reword",
    "wording",
    "prompt",
    "text",
    "draft",
    "changelog",
    "docs",
    "documentation",
    "readme",
    "overview",
    "release",
    "notes",
    "concise",
}

_AGENT_HINTS = [
    "edit this file",
    "create a file",
    "delete this file",
    "rename this file",
    "run this command",
    "execute this command",
    "fix this bug",
    "change this function",
    "refactor this",
]

_PLAN_HINTS = [
    "new app",
    "new project",
    "build me a",
    "build a new",
    "create a new app",
    "create a new project",
    "think through",
    "think about how",
    "plan this out",
    "plan this for me",
    "plan out",
    "let's plan",
    "lets plan",
]

_PLAN_ACTION_KEYWORDS = {
    "build", "create", "implement", "design", "develop", "architect", "scaffold",
}


def should_trigger_plan_mode(user_input: str) -> bool:
    """Return True if the message contains clear planning intent (keyword-driven trigger)."""
    text = (user_input or "").strip().lower()
    if not text:
        return False
    if _has_phrase(text, _PLAN_HINTS):
        return True
    tokens = set(re.findall(r"[a-z0-9_]+", text))
    if ("plan" in tokens or "think" in tokens) and _PLAN_ACTION_KEYWORDS & tokens:
        return True
    return False


def _has_phrase(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def _ext_present(text: str, ext: str) -> bool:
    """Return True only if ext appears as a standalone token, not as a substring of a word."""
    return f" {ext}" in text or text.startswith(ext)


def _has_file_op_intent(text: str, tokens: set[str]) -> bool:
    """
    Heuristic to detect if the user intends to perform a file operation.

    Matches choices:
    - _ext_present: Uses word-boundary check (leading space or start of string) to avoid
      false positives on file extensions inside words (e.g., 'copy' containing '.py' isn't a match).
    - _has_phrase: Uses substring matching for common intent patterns like 'write to ' or 'in file'.
    """
    if (_ext_present(text, ".py") or _ext_present(text, ".md") or _ext_present(text, ".txt")
            or _ext_present(text, ".js") or _ext_present(text, ".ts") or _ext_present(text, ".html")
            or _ext_present(text, ".css") or _ext_present(text, ".json")):
        return True
    if _has_phrase(text, ["write to ", "in file", "file ", "path ", "make changes", "make a change"]):
        return True
    has_action = any(k in tokens for k in {
        "edit", "create", "delete", "rename", "write", "change", "changes",
        "fix", "implement", "refactor", "update", "modify", "add",
    })
    has_target = any(k in tokens for k in {
        "file", "function", "path", "code",
        "codebase", "module", "project", "app",
    })
    return has_action and has_target


def _has_shell_intent(tokens: set[str]) -> bool:
    return any(k in tokens for k in {"run", "execute", "install", "shell", "command"})


def _is_code_explain_request(text: str, tokens: set[str]) -> bool:
    if "explain" not in tokens:
        return False
    if any(k in tokens for k in {"code", "codebase", "module", "function", "architecture", "app", "project"}):
        return True
    return _has_phrase(text, ["how this code works", "how the code works", "how this app works"])


def _is_prompt_generation_request(tokens: set[str]) -> bool:
    return "prompt" in tokens and any(k in tokens for k in {"write", "generate", "create", "draft"})


def _score_request_route(user_input: str) -> tuple[int, int, int]:
    text = (user_input or "").strip().lower()
    if not text:
        return 0, 0, 0

    inv_score = 0
    compose_score = 0
    agent_score = 0

    for phrase in _INVESTIGATION_HINTS:
        if phrase in text:
            inv_score += 3
    for phrase in _COMPOSE_HINTS:
        if phrase in text:
            compose_score += 3
    for phrase in _AGENT_HINTS:
        if phrase in text:
            agent_score += 3

    tokens = set(re.findall(r"[a-z0-9_]+", text))

    if "codebase" in tokens or "project" in tokens:
        inv_score += 1
    if "debug" in tokens and "why" in tokens:
        inv_score += 2
    if "explain" in tokens and ("handles" in tokens or "works" in tokens):
        inv_score += 2
    if _is_code_explain_request(text, tokens):
        inv_score += 3
    if "explain" in tokens and not _is_code_explain_request(text, tokens):
        compose_score += 1
    if _is_prompt_generation_request(tokens):
        compose_score += 3

    inv_score += sum(1 for k in _INVESTIGATION_KEYWORDS if k in tokens)
    compose_score += sum(1 for k in _COMPOSE_KEYWORDS if k in tokens)
    agent_score += sum(1 for k in _AGENT_KEYWORDS if k in tokens)

    has_file_op = _has_file_op_intent(text, tokens)
    has_shell = _has_shell_intent(tokens)
    if has_file_op or has_shell:
        agent_score += 4
        if compose_score > 0:
            # Penalty heuristic: if we detect intent for a tool (file/shell),
            # it's unlikely to be purely a 'compose' (text generation) task.
            compose_score = max(1, compose_score - 1)
        # File/shell intent means the user wants to *act*, not just research.
        # Investigation mode blocks writes, so pull it back.
        inv_score = max(0, inv_score - 4)

    return inv_score, compose_score, agent_score


def classify_request_route(user_input: str) -> str:
    inv_score, compose_score, agent_score = _score_request_route(user_input)
    if inv_score >= max(compose_score, agent_score) + 2:
        return "investigation"
    if compose_score > agent_score:
        return "compose"
    return "agent"


def _route_registry() -> dict[str, RouteHandler]:
    return {
        "agent": run_agent_route,
        "compose": run_compose_route,
        "investigation": run_investigation_route,
    }


def run_agent_route(app, _user_input: str) -> None:
    app._run_ai_turn()


def run_investigation_route(app, user_input: str) -> None:
    app._run_investigation_turn(user_input)


def run_compose_route(app, user_input: str) -> None:
    app._run_compose_turn(user_input)


def run_routed_turn(app, user_input: str) -> None:
    if not state.ui.plan_executing:
        if not state.ui.plan_mode and should_trigger_plan_mode(user_input):
            state.ui.plan_mode_this_turn = True

    route = classify_request_route(user_input)
    handler = _route_registry().get(route, run_agent_route)
    handler(app, user_input)
