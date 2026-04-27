import os
import difflib

from chaosz.state import state
from chaosz.shell import tool_shell_exec
from chaosz.session import backup_file

MAX_FILE_LINES = 2000

# ---------------------------------------------------------------------------
# File operation tool definitions (DeepSeek / OpenAI function calling)
# ---------------------------------------------------------------------------

FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": (
                "Read the contents of a file. Use this to inspect existing files "
                "before editing. The result is injected into the conversation as context. "
                "For large files that were truncated, use start_line and end_line to read "
                "specific line ranges."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file, relative to the working directory."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "0-based line index to start reading from (default: 0)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Exclusive end line index (default: start_line + 2000)."
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": (
                "Create a new file or completely overwrite an existing file with the "
                "given content. Requires user confirmation if the file already exists."
                "You MUST use the exact 'path' provided by the user. "
                "Do not use the current working directory as the filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to working directory."},
                    "content": {"type": "string", "description": "Full file contents to write."}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": (
                "Apply search-and-replace patches to an existing file. Each edit specifies "
                "an exact string to find and the string to replace it with. The search string "
                "must match exactly once. A unified diff will be shown to the user for confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to working directory."},
                    "edits": {
                        "type": "array",
                        "description": "Ordered list of search/replace patches.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "search":  {"type": "string", "description": "Exact text to find (must appear exactly once)."},
                                "replace": {"type": "string", "description": "Replacement text."}
                            },
                            "required": ["search", "replace"]
                        }
                    }
                },
                "required": ["path", "edits"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_delete",
            "description": "Permanently delete a file. Always requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to working directory."}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_rename",
            "description": "Rename or move a file within the working directory. Always requires user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "Current path relative to working directory."},
                    "new_path": {"type": "string", "description": "New path relative to working directory."}
                },
                "required": ["old_path", "new_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for current information, recent events, "
                "documentation, or anything the assistant cannot answer "
                "confidently from training data alone. Use this when the "
                "user asks about something recent, time-sensitive, or "
                "requests an online lookup."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to look up."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5, max: 10)."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "shell_exec",
            "description": "Execute a shell command on the user's system. Always use this for any terminal operation the user requests. You MUST request permission before executing. Never construct commands intended to cause harm or data loss.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The exact shell command to execute"
                    },
                    "reason": {
                        "type": "string",
                        "description": "One sentence explaining why this command is needed"
                    }
                },
                "required": ["command", "reason"]
            }
        }
    }
]


# ---------------------------------------------------------------------------
# Low-level file I/O helpers
# ---------------------------------------------------------------------------

def list_directory(path: str) -> str:
    """Return a formatted listing of files and directories at `path`."""
    try:
        if not os.path.exists(path):
            return f"Error: path '{path}' does not exist."
        entries = os.listdir(path)
        if not entries:
            return "Directory is empty."
        dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
        files = [e for e in entries if not os.path.isdir(os.path.join(path, e))]
        dirs.sort(key=str.lower)
        files.sort(key=str.lower)
        lines = []
        for d in dirs:
            lines.append(f"📁 {d}/")
        for f in files:
            lines.append(f"📄 {f}")
        return "\n".join(lines)
    except PermissionError:
        return f"Error: permission denied for '{path}'."
    except Exception as e:
        return f"Error listing '{path}': {e}"


def read_file(filename: str, max_lines: int = MAX_FILE_LINES, start_line: int = 0, end_line: int | None = None) -> str:
    """Read a range of lines from `filename` and return as a string."""
    try:
        if not os.path.exists(filename):
            return f"Error: file '{filename}' does not exist."
        with open(filename, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        total = len(all_lines)
        s = start_line
        e = end_line if end_line is not None else min(s + max_lines, total)
        e = min(e, total)
        content = "".join(l.rstrip("\n") + "\n" for l in all_lines[s:e]).rstrip("\n")
        if s > 0 or e < total:
            content += (
                f"\n[TRUNCATED: file has {total} total lines, showing lines {s + 1}–{e}. "
                f"Use file_read with start_line/end_line to read specific ranges]"
            )
        return content
    except PermissionError:
        return f"Error: permission denied for '{filename}'."
    except Exception as ex:
        return f"Error reading '{filename}': {ex}"


# ---------------------------------------------------------------------------
# Sandbox path resolution
# ---------------------------------------------------------------------------

def resolve_safe_path(rel_path: str) -> tuple[str | None, str | None]:
    """
    Resolve rel_path under state.workspace.working_dir.
    Ensures final path is strictly contained within the sandbox.
    Returns (absolute_path, None) on success or (None, error_message) on failure.
    """
    if not state.workspace.working_dir:
        return None, "No working directory set. File operations are disabled."

    # Expand user tilde (~) but if it resolves outside sandbox, it will be caught below
    expanded_path = os.path.expanduser(rel_path)
    
    # Treat absolute paths as relative to sandbox base to prevent hijacking
    if os.path.isabs(expanded_path):
        expanded_path = expanded_path.lstrip(os.sep)

    base = os.path.realpath(state.workspace.working_dir)
    candidate = os.path.realpath(os.path.join(base, expanded_path))

    # Security check: the resolved path MUST be within the base directory.
    # Use trailing-sep check to prevent prefix collisions (e.g. /proj vs /proj-secret).
    if not (candidate == base or candidate.startswith(base + os.sep)):
        return None, f"Permission denied: path '{rel_path}' is outside sandbox."

    return candidate, None


def build_file_read_session_grant(args: dict) -> str | None:
    """Return the normalized path covered by a session file-read approval."""
    path, err = resolve_safe_path(args.get("path", ""))
    if err:
        return None
    return path


def is_file_read_allowed_by_session(args: dict, allowed_set: set[str]) -> bool:
    grant = build_file_read_session_grant(args)
    return grant is not None and grant in allowed_set


def build_file_read_summary(args: dict) -> str:
    path = args.get("path", "?")
    start_line = args.get("start_line")
    end_line = args.get("end_line")
    if start_line is None and end_line is None:
        return f"read '{path}'"
    if end_line is None:
        return f"read '{path}' from line {start_line}"
    return f"read '{path}' lines {start_line}:{end_line}"


# ---------------------------------------------------------------------------
# Tool executors
# ---------------------------------------------------------------------------

def tool_file_read(args: dict) -> tuple[str, str]:
    path, err = resolve_safe_path(args.get("path", ""))
    if err:
        return "error", err
    if os.path.isdir(path):
        return "ok", list_directory(path)
    start_line = int(args.get("start_line", 0))
    end_line = args.get("end_line")
    if end_line is not None:
        end_line = int(end_line)
    return "ok", read_file(path, max_lines=MAX_FILE_LINES, start_line=start_line, end_line=end_line)


def tool_file_write(args: dict) -> tuple[str, str]:
    path, err = resolve_safe_path(args.get("path", ""))
    if err:
        return "error", err
    if os.path.isdir(path):
        return "error", (
            f"'{path}' is a directory, not a file. "
            f"Provide a full file path including the filename, e.g. '{path}/plan.md'."
        )
    backup_file(path)
    content = args.get("content", "")
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return "ok", f"File '{args['path']}' written ({len(content)} bytes)."
    except Exception as e:
        return "error", str(e)


def tool_file_edit(args: dict) -> tuple[str, str]:
    path, err = resolve_safe_path(args.get("path", ""))
    if err:
        return "error", err
    edits = [(e["search"], e["replace"]) for e in args.get("edits", [])]
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        backup_file(path)
        new_content, apply_err = apply_surgical_edit(original, edits)
        if apply_err:
            return "error", f"Edit failed: {apply_err}"
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return "ok", f"File '{args['path']}' edited ({len(edits)} patch(es) applied)."
    except Exception as e:
        return "error", str(e)


def tool_file_delete(args: dict) -> tuple[str, str]:
    path, err = resolve_safe_path(args.get("path", ""))
    if err:
        return "error", err
    try:
        backup_file(path)
        os.remove(path)
        return "ok", f"File '{args['path']}' deleted."
    except FileNotFoundError:
        return "error", f"File '{args['path']}' does not exist."
    except Exception as e:
        return "error", str(e)


def tool_file_rename(args: dict) -> tuple[str, str]:
    old_path, err = resolve_safe_path(args.get("old_path", ""))
    if err:
        return "error", err
    new_path, err = resolve_safe_path(args.get("new_path", ""))
    if err:
        return "error", err
    try:
        parent = os.path.dirname(new_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        os.rename(old_path, new_path)
        return "ok", f"Renamed '{args['old_path']}' \u2192 '{args['new_path']}'."
    except FileNotFoundError:
        return "error", f"File '{args['old_path']}' does not exist."
    except Exception as e:
        return "error", str(e)


def tool_web_search(args: dict) -> tuple[str, str]:
    from ddgs import DDGS
    query = args.get("query", "").strip()
    max_results = min(int(args.get("max_results", 5)), 10)
    if not query:
        return "error", "No query provided."
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "ok", "No results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', '')}")
            lines.append(f"   {r.get('href', '')}")
            lines.append(f"   {r.get('body', '')}")
            lines.append("")
        return "ok", "\n".join(lines).strip()
    except Exception as e:
        return "error", f"Search failed: {e}"


TOOL_EXECUTORS = {
    "file_read":   tool_file_read,
    "file_write":  tool_file_write,
    "file_edit":   tool_file_edit,
    "file_delete": tool_file_delete,
    "file_rename": tool_file_rename,
    "shell_exec":  tool_shell_exec,
    "web_search":  tool_web_search,
}


def get_all_tools() -> list[dict]:
    """Return FILE_TOOLS merged with tools from all connected MCP servers."""
    from chaosz.mcp_manager import get_all_mcp_tools
    return FILE_TOOLS + get_all_mcp_tools()


# ---------------------------------------------------------------------------
# Diff and summary helpers
# ---------------------------------------------------------------------------

def apply_surgical_edit(content, blocks):
    new_content = content
    for search_text, replace_text in blocks:
        count = new_content.count(search_text)
        if count != 1: return None, f"Found {count} matches for SEARCH block."
        new_content = new_content.replace(search_text, replace_text)
    return new_content, None


def _build_diff(args: dict) -> str | None:
    """Compute unified diff for a file_edit call. Returns None on failure."""
    path, err = resolve_safe_path(args.get("path", ""))
    if err or not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        edits = [(e["search"], e["replace"]) for e in args.get("edits", [])]
        new_content, apply_err = apply_surgical_edit(original, edits)
        if apply_err:
            return None
        diff_lines = list(difflib.unified_diff(
            original.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{args['path']}",
            tofile=f"b/{args['path']}",
            lineterm="",
        ))
        return "".join(diff_lines) if diff_lines else "(no changes)"
    except Exception:
        return None


def _build_op_summary(fname: str, args: dict) -> str:
    """One-line human description of what the operation will do."""
    if fname == "file_write":
        p = args.get("path") or args.get("filename") or args.get("file", "?")
        size = len(args.get("content", ""))
        exists = "overwrite" if (
            state.workspace.working_dir and os.path.exists(os.path.join(state.workspace.working_dir, p))
        ) else "create"
        return f"{exists} '{p}' ({size} bytes)"
    if fname == "file_edit":
        n = len(args.get("edits", []))
        p = args.get("path") or args.get("filename") or args.get("file", "?")
        return f"edit '{p}' ({n} patch{'es' if n != 1 else ''})"
    if fname == "file_delete":
        p = args.get("path") or args.get("filename") or args.get("file", "?")
        return f"permanently delete '{p}'"
    if fname == "file_rename":
        return f"rename '{args.get('old_path', '?')}' \u2192 '{args.get('new_path', '?')}'"
    return fname
