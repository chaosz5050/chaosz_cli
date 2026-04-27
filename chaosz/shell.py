import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime

from chaosz.config import CHAOSZ_DIR
from chaosz.state import state

ALWAYS_PROMPT_COMMANDS = {
    "sudo", "rm", "rmdir", "dd", "mkfs", "fdisk", "chmod", "chown",
    "pacman -S", "pacman -R", "pacman -U", "pacman -Syu",
    "systemctl start", "systemctl stop", "systemctl enable", "systemctl disable",
    "mkswap", "swapon", "shred", "wipefs"
}

DANGEROUS_OPS = {"|", ">", "<", "&", ";", "$", "`"}
PATTERN_REUSE_CMDS = {"cat", "ls", "tree", "head", "tail"}


@dataclass(frozen=True)
class ShellReadGrant:
    command: str
    options: tuple[str, ...]
    directory: str
    glob_shape: str


def _has_shell_control(command: str) -> bool:
    return any(op in command for op in DANGEROUS_OPS)


def _parse_shell_words(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _simple_glob_shape(pattern: str) -> str | None:
    if pattern.count("*") != 1:
        return None
    if pattern == "*":
        return None
    if any(ch in pattern for ch in "?[]{}"):
        return None
    if pattern.endswith("*"):
        return "trailing-star"
    if pattern.startswith("*"):
        return "leading-star"
    return "middle-star"


def _resolve_workspace_target(target: str) -> tuple[str, str] | None:
    """Return (directory, basename_pattern) if target stays inside the workspace."""
    if not state.workspace.working_dir:
        return None

    expanded = os.path.expanduser(target)
    base = os.path.realpath(state.workspace.working_dir)
    joined = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
    raw_dir, basename = os.path.split(joined)
    if not basename:
        return None

    directory = os.path.realpath(raw_dir or base)
    if directory != base and not directory.startswith(base + os.sep):
        return None
    return directory, basename


def _build_read_grant(command: str) -> ShellReadGrant | None:
    if _has_shell_control(command):
        return None

    words = _parse_shell_words(command)
    if not words:
        return None

    base_cmd = os.path.basename(words[0])
    if base_cmd not in PATTERN_REUSE_CMDS:
        return None

    options: list[str] = []
    targets: list[str] = []
    for word in words[1:]:
        if word.startswith("-"):
            options.append(word)
        else:
            targets.append(word)

    if len(targets) != 1:
        return None

    resolved = _resolve_workspace_target(targets[0])
    if not resolved:
        return None
    directory, basename = resolved
    glob_shape = _simple_glob_shape(basename)
    if not glob_shape:
        return None

    return ShellReadGrant(
        command=base_cmd,
        options=tuple(options),
        directory=directory,
        glob_shape=glob_shape,
    )


def build_shell_session_grants(command: str) -> set:
    """Build session approvals for a user-approved shell command."""
    if _has_shell_control(command):
        return set()

    grants: set = {command}
    read_grant = _build_read_grant(command)
    if read_grant:
        grants.add(read_grant)
    return grants


def is_command_allowed_by_session(command: str, allowed_set: set) -> bool:
    """Check if command is allowed by exact or pattern-scoped session grants."""
    if _has_shell_control(command):
        return False

    if command in allowed_set:
        return True

    read_grant = _build_read_grant(command)
    return read_grant is not None and read_grant in allowed_set


def is_always_prompt_command(command: str) -> bool:
    """Return True only when a genuinely dangerous command appears as an actual
    command token — not as a substring of a path, argument, or word."""
    segments = re.split(r'&&|\|\||;|\|', command)
    for segment in segments:
        words = segment.strip().split()
        if not words:
            continue
        cmd_name = os.path.basename(words[0])
        for dangerous in ALWAYS_PROMPT_COMMANDS:
            d_words = dangerous.split()
            if cmd_name == d_words[0]:
                if len(d_words) == 1 or words[1:len(d_words)] == d_words[1:]:
                    return True
    return False


def _setup_session_logs() -> str:
    """Setup rotating session logs in logs/ directory.
    Returns path to session1.log for this session."""
    logs_dir = os.path.join(CHAOSZ_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Rotate logs: session3.log → delete, session2.log → session3.log, session1.log → session2.log
    session3 = os.path.join(logs_dir, "session3.log")
    session2 = os.path.join(logs_dir, "session2.log")
    session1 = os.path.join(logs_dir, "session1.log")

    if os.path.exists(session3):
        os.remove(session3)
    if os.path.exists(session2):
        os.rename(session2, session3)
    if os.path.exists(session1):
        os.rename(session1, session2)

    # Create fresh session1.log with header
    with open(session1, "w", encoding="utf-8") as f:
        f.write(f"=== Chaosz CLI Session Log ===\n")
        f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"================================\n\n")

    return session1


def _write_shell_to_log(command: str, exit_code: int, stdout: str, stderr: str) -> None:
    """Write shell command execution to session log file."""
    if not state.session.log_path:
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Check if file exceeds 1MB and truncate oldest 20% if needed
    try:
        if os.path.exists(state.session.log_path):
            file_size = os.path.getsize(state.session.log_path)
            if file_size > 1_000_000:  # 1MB
                with open(state.session.log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                # Keep bottom 80% of lines
                keep_from = int(len(lines) * 0.2)
                with open(state.session.log_path, "w", encoding="utf-8") as f:
                    f.writelines(lines[keep_from:])
    except Exception:
        pass  # Don't crash if log rotation fails

    # Write new entry
    try:
        with open(state.session.log_path, "a", encoding="utf-8") as f:
            f.write(f"\n=== {timestamp} ===\n")
            f.write(f"Command: {command}\n")
            f.write(f"Exit code: {exit_code}\n")
            f.write(f"--- stdout ---\n")
            f.write(stdout)
            if stdout and not stdout.endswith("\n"):
                f.write("\n")
            if stderr:
                f.write(f"--- stderr ---\n")
                f.write(re.sub(r'\[sudo\] password for \S+:', '[sudo] password:', stderr))
                if not stderr.endswith("\n"):
                    f.write("\n")
            f.write(f"===============================\n")
    except Exception:
        pass  # Silently fail if log writing fails


def tool_shell_exec(args: dict) -> tuple[str, str]:
    """Execute shell command. Uses state.permissions.sudo_password if set for sudo commands."""
    command = args.get("command", "")
    password = state.permissions.sudo_password
    try:
        if password is not None and command.strip().startswith("sudo "):
            # Insert -S flag after sudo, preserving any existing flags
            command = re.sub(r'^sudo\b', 'sudo -S', command, count=1)
            # Pass password via stdin
            proc = subprocess.run(
                command,
                shell=True,
                input=password + "\n",
                capture_output=True,
                text=True,
                timeout=30,
                cwd=state.workspace.working_dir if state.workspace.working_dir else None
            )
            # Clear password after use, even if command fails
            state.permissions.sudo_password = None
        else:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=state.workspace.working_dir if state.workspace.working_dir else None
            )
        output = proc.stdout
        if proc.stderr:
            output += f"\n[stderr]\n{proc.stderr}"
        status = "ok" if proc.returncode == 0 else "error"
        # Write to session log
        _write_shell_to_log(command, proc.returncode, proc.stdout, proc.stderr)
        return status, output
    except subprocess.TimeoutExpired:
        # Clear password on timeout as well
        if password is not None:
            state.permissions.sudo_password = None
        # Write to session log
        _write_shell_to_log(command, -1, "", "Command timed out after 30 seconds")
        return "error", "Command timed out after 30 seconds"
    except Exception as e:
        if password is not None:
            state.permissions.sudo_password = None
        # Write to session log
        _write_shell_to_log(command, -1, "", f"Execution failed: {e}")
        return "error", f"Execution failed: {e}"
