import os


PRESET_SKILLS = {
    "coder": """You are in Coder mode. Your primary focus is writing clean, production-ready code.

- Always read the relevant file(s) before making any changes
- Prefer editing existing files over creating new ones
- Write minimal, focused changes — no scope creep beyond the task
- Never add comments, docstrings, or type hints to code you didn't change
- After completing file operations, summarize exactly what changed and why
- Flag any assumptions you make about the codebase before acting on them
- If a task spans multiple files, tackle one at a time and confirm each step""",

    "code-review": """You are in Code Review mode. Review code systematically — never just approve it.

For every review, check in this order:
1. Security — injection risks, exposed secrets, unsafe operations, input validation
2. Correctness — edge cases, off-by-one errors, null/empty handling, error paths
3. Performance — unnecessary loops, blocking calls, memory leaks, N+1 queries
4. Maintainability — readability, naming clarity, cyclomatic complexity
5. Test coverage — what is untested that clearly should be

Output findings as a numbered list. Tag each with severity:
  [critical]   — must fix before merge
  [warning]    — should fix; explain why if skipping
  [suggestion] — optional improvement

For every finding: state the problem, show the relevant code, propose a concrete fix.
End your review with a one-line verdict: APPROVE / APPROVE WITH CHANGES / REJECT""",

    "mcp-builder": """You are in MCP Builder mode. You are building Model Context Protocol (MCP) servers.

MCP servers expose tools, resources, and prompts to AI assistants via JSON-RPC 2.0 over stdio.

Key conventions:
- Use the official `mcp` Python package: pip install mcp
- Define tools with @server.call_tool(); tools return list[TextContent | ImageContent]
- Declare tool schemas in @server.list_tools() using InputSchema (JSON Schema format)
- Define resources with @server.read_resource()
- Define prompts with @server.get_prompt()
- Raise McpError(ErrorCode.InvalidRequest, "message") for user-facing errors
- Raise McpError(ErrorCode.InternalError, str(e)) for unexpected exceptions
- Run with: mcp.run(server, transport="stdio")
- Test locally with: mcp dev server.py

Before writing any server code, read existing server files to match the patterns in use.
State any assumptions about external APIs or data sources before implementing.""",
}


def get_skills_dir() -> str:
    """Return the global skills directory path under ~/.config/chaosz/skills."""
    from chaosz.config import CHAOSZ_DIR
    return os.path.join(CHAOSZ_DIR, "skills")


def ensure_skills_dir() -> None:
    """Create skills directory and write preset skills if not already present."""
    skills_dir = get_skills_dir()
    os.makedirs(skills_dir, exist_ok=True)
    for name, content in PRESET_SKILLS.items():
        path = os.path.join(skills_dir, f"{name}.md")
        if not os.path.exists(path):
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except OSError:
                pass


def list_skills() -> list[str]:
    """Return sorted list of skill names (filenames without .md extension)."""
    skills_dir = get_skills_dir()
    try:
        names = [
            f[:-3] for f in os.listdir(skills_dir)
            if f.endswith(".md") and os.path.isfile(os.path.join(skills_dir, f))
        ]
        return sorted(names)
    except OSError:
        return []


def load_skill(name: str) -> str:
    """Read and return skill content. Returns empty string on failure."""
    path = os.path.join(get_skills_dir(), f"{name}.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_skill(name: str, content: str) -> None:
    """Write skill content to skills/<name>.md in the working directory."""
    skills_dir = get_skills_dir()
    os.makedirs(skills_dir, exist_ok=True)
    path = os.path.join(skills_dir, f"{name}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def delete_skill(name: str) -> bool:
    """Delete skills/<name>.md. Returns True on success, False if not found."""
    path = os.path.join(get_skills_dir(), f"{name}.md")
    try:
        os.remove(path)
        return True
    except OSError:
        return False
