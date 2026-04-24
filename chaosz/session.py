import json
import os
import re
from datetime import datetime, timezone, timedelta

from chaosz.config import CHAOSZ_DIR
from chaosz.state import state

CONTEXT_DIR  = os.path.join(CHAOSZ_DIR, "context")
ARCHIVE_DIR  = os.path.join(CHAOSZ_DIR, "archive")
_MEMORY_FILE = os.path.join(CHAOSZ_DIR, "memory.json")
_MAX_SESSIONS = 5
_ARCHIVE_MAX_DAYS = 5


def _ensure_dirs() -> None:
    os.makedirs(CONTEXT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def _log_error(msg: str) -> None:
    """Write an error line to the session log if one is configured."""
    if not state.session.log_path:
        return
    try:
        with open(state.session.log_path, "a") as f:
            f.write(f"{msg}\n")
    except OSError:
        pass


def _session_path(n: int) -> str:
    return os.path.join(CONTEXT_DIR, f"session_{n:03d}.json")


LIVE_SESSION = _session_path(1)


def _rotate_sessions() -> None:
    """Move session_005 to archive if it exists, then rotate 004→005 … 001→002."""
    oldest = _session_path(_MAX_SESSIONS)
    if os.path.exists(oldest):
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        archive_name = f"session_{date_str}.json"
        archive_path = os.path.join(ARCHIVE_DIR, archive_name)
        counter = 1
        while os.path.exists(archive_path):
            archive_name = f"session_{date_str}_{counter}.json"
            archive_path = os.path.join(ARCHIVE_DIR, archive_name)
            counter += 1
        os.rename(oldest, archive_path)

    for n in range(_MAX_SESSIONS - 1, 0, -1):
        src = _session_path(n)
        if os.path.exists(src):
            os.rename(src, _session_path(n + 1))


def _prune_archive() -> None:
    """Delete archive files older than _ARCHIVE_MAX_DAYS days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=_ARCHIVE_MAX_DAYS)
    for fname in os.listdir(ARCHIVE_DIR):
        fpath = os.path.join(ARCHIVE_DIR, fname)
        if not os.path.isfile(fpath):
            continue
        mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
        if mtime < cutoff:
            try:
                os.remove(fpath)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Live context streaming
# ---------------------------------------------------------------------------

def init_live_session() -> None:
    """Create session_001.json with a fresh header. Called once at startup."""
    data = {
        "session_start": datetime.now(timezone.utc).isoformat(),
        "active_project": state.workspace.working_dir,
        "messages": [],
    }
    try:
        with open(LIVE_SESSION, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        _log_error(f"ERROR init_live_session: {e}")


def append_to_live_session(role: str, content: str) -> None:
    """Append one message to session_001.json messages array. Silently skips on error."""
    if not os.path.exists(LIVE_SESSION):
        return
    with state.session.lock:
        try:
            with open(LIVE_SESSION, "r") as f:
                data = json.load(f)
            data["messages"].append({
                "role": role,
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            with open(LIVE_SESSION, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            _log_error(f"ERROR append_to_live_session: {e}")


# ---------------------------------------------------------------------------
# Startup cleanup
# ---------------------------------------------------------------------------

def startup_cleanup() -> None:
    """Remove stale lock, rotate any existing session_001, create fresh one."""
    lock = os.path.join(CHAOSZ_DIR, ".reflecting.lock")
    if os.path.exists(lock):
        try:
            os.remove(lock)
        except OSError:
            pass
    _ensure_dirs()
    if os.path.exists(_session_path(1)):
        _rotate_sessions()
    init_live_session()
    _prune_archive()


# ---------------------------------------------------------------------------
# Reflection pass
# ---------------------------------------------------------------------------

def run_reflection_pass(app) -> bool:
    """
    Read live context + current memory, make one AI call to update memory,
    then collapse session_001.json messages into a summary entry.
    Returns True on success, False if skipped or failed.
    Must be called from a background thread.
    """
    from chaosz.config import VALID_CATEGORIES
    from chaosz.providers import build_api_params, get_client, get_native_ollama_client

    # Read live session
    if not os.path.exists(LIVE_SESSION):
        return False
    with state.session.lock:
        try:
            with open(LIVE_SESSION, "r") as f:
                session_data = json.load(f)
        except Exception:
            return False

    messages = session_data.get("messages", [])
    # Filter out previous reflection summaries — only feed real conversation
    real_messages = [m for m in messages if m.get("role") != "reflection_summary"]
    if not real_messages:
        return False

    # Read current memory
    try:
        with open(_MEMORY_FILE, "r") as f:
            current_memory = json.load(f)
    except Exception as e:
        _log_error(f"ERROR reflection reading memory file: {e}")
        current_memory = {cat: [] for cat in VALID_CATEGORIES}

    messages_text = json.dumps(real_messages, indent=2)
    memory_text = json.dumps(current_memory, indent=2)

    system_msg = (
        "You are a memory management assistant for Chaosz CLI.\n"
        "Return only valid JSON. No markdown fences. No explanation."
    )

    prompt = (
        f"RECENT CONVERSATION:\n{messages_text}\n\n"
        f"CURRENT MEMORY:\n{memory_text}\n\n"
        "INSTRUCTIONS:\n\n"
        "CATEGORIES — return exactly these five, always present even\n"
        "if empty arrays:\n\n"
        "about_user: PROTECTED — biographical facts: name, age, location,\n"
        "  hobbies, personality traits. NEVER remove existing entries.\n"
        "  Copy ALL current about_user entries to the output unchanged.\n"
        "  You may only ADD new entries found in the conversation.\n"
        "  New entries must be permanent facts (not session events).\n"
        "  Max 8 entries.\n\n"
        "preferences: how the user likes to work. Tools they use\n"
        "  consistently, workflow style, persistent opinions.\n"
        "  Includes technical skills and tool knowledge.\n"
        "  NOT temporary preferences. Max 5 entries.\n\n"
        "projects: one entry per active project. One sentence maximum.\n"
        "  Update in place, never duplicate. Max 5 entries.\n\n"
        "workspace_context: codebase rules, architectural decisions,\n"
        "  project conventions, tech stack details. Max 5 entries.\n\n"
        "top_of_mind: current session focus only. Completely replaced\n"
        "  every pass. Empty if nothing significant happened.\n"
        "  Max 3 entries.\n\n"
        "summary: A structured handoff document for the next session. The model\n"
        "  reading this will have no other conversation history. Use this format:\n\n"
        "  CURRENT TASK: one sentence — what the user is working on right now.\n"
        "  FILES: list each file touched this session with a brief note on its state.\n"
        "  DECISIONS: key technical choices made or constraints the user stated.\n"
        "  NEXT STEP: where things were left off or what comes next.\n\n"
        "  Aim for 100-200 words. Be specific — include file paths, function names,\n"
        "  variable names. Do not pad. Do not omit specifics to stay short.\n\n"
        "PRUNING RULES — remove any entry that:\n"
        "- Contains \"recently\", \"today\", \"discussed\", \"asked about\"\n"
        "- Describes a one-off event or action\n"
        "- Is a duplicate or subset of another entry in any category\n"
        "- Sits in the wrong category per the definitions above\n"
        "- Contains \"would like to\" where intent has been fulfilled\n"
        "- References a path or file that may no longer exist\n\n"
        "PROTECTED — never remove entries from about_user. Copy every\n"
        "  existing about_user entry verbatim into the output.\n\n"
        "LANGUAGE: English only, regardless of conversation language.\n\n"
        "Return the complete updated memory object as valid JSON only."
    )

    try:
        if state.provider.active == "ollama":
            ollama_client = get_native_ollama_client()
            response = ollama_client.chat(
                model=state.provider.model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
                format="json",
            )
            raw = response.get("message", {}).get("content", "").strip()
        else:
            client = get_client()
            params = build_api_params(
                state.provider.active,
                state.provider.model,
                [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                stream=False,
            )
            params["timeout"] = 30
            params["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**params)
            raw = response.choices[0].message.content.strip()

        updated_data = json.loads(raw)

        # Validate: must be a dict; backfill any missing categories
        if not isinstance(updated_data, dict):
            return False

        # Extract summary and update memory object
        rolling_summary = updated_data.get("summary", "Context refreshed.")
        updated_memory = {cat: updated_data.get(cat, []) for cat in VALID_CATEGORIES}

        # about_user is protected — union original entries back in so AI can only add, never remove
        original_about = current_memory.get("about_user", [])
        ai_about = updated_memory.get("about_user", [])
        updated_memory["about_user"] = list(dict.fromkeys(original_about + ai_about))

        # Backfill from current_memory if any category is missing or wrong type
        for cat in VALID_CATEGORIES:
            if not isinstance(updated_memory[cat], list):
                updated_memory[cat] = current_memory.get(cat, [])

        # Write updated memory
        with open(_MEMORY_FILE, "w") as f:
            json.dump(updated_memory, f, indent=2)
        state.reasoning.memory = updated_memory

        # Collapse the on-disk session file to the rolling summary so restarts
        # don't load a huge session, but leave state.session.messages intact so
        # the live conversation context is preserved until actual compaction.
        ts = datetime.now(timezone.utc).isoformat()
        with state.session.lock:
            session_data["messages"] = [{
                "role": "reflection_summary",
                "content": rolling_summary,
                "timestamp": ts,
            }]
            session_data["last_reflection"] = ts
            with open(LIVE_SESSION, "w") as f:
                json.dump(session_data, f, indent=2)

        return True

    except Exception as e:
        # Log failure if possible; leave memory and session untouched
        if state.session.log_path:
            try:
                with open(state.session.log_path, "a") as f:
                    f.write(f"REFLECTION FAILED: {e}\n")
            except OSError:
                pass
        from rich.text import Text
        app.call_from_thread(
            app._write, "",
            Text("⚠ Reflection pass failed — context not updated.", style="dim yellow"),
        )
        return False


# ---------------------------------------------------------------------------
# Session restore on startup
# ---------------------------------------------------------------------------

def restore_session() -> None:
    """Load session_001.json into state.messages on startup.

    reflection_summary entries are mapped to a [user, assistant] pair so they
    are valid API messages. tool/tool_result entries are skipped because their
    tool_call_ids no longer exist in the new session.
    """
    if not os.path.exists(LIVE_SESSION):
        return
    try:
        with open(LIVE_SESSION, "r") as f:
            data = json.load(f)
    except Exception:
        return

    messages = data.get("messages", [])
    if not messages:
        return

    restored = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "")
        if role == "reflection_summary":
            restored.append({"role": "user", "content": f"[REFLECTION SUMMARY] {content}"})
            restored.append({"role": "assistant", "content": "Understood. Continuing from where we left off."})
        elif role in ("user", "assistant"):
            if role == "assistant" and m.get("tool_calls"):
                # Strip tool_calls — the corresponding tool results won't be in the
                # restored session, so including them produces dangling tool_call_ids
                # that cause API 400 errors on the next call.
                if content:
                    restored.append({"role": "assistant", "content": content})
                # tool-only assistant turns (no content) are skipped entirely
            else:
                restored.append({"role": role, "content": content})

    state.session.messages = restored


# ---------------------------------------------------------------------------
# Exit-time session summary (kept from Phase 1)
# ---------------------------------------------------------------------------

def generate_and_save_session(app) -> bool:
    """
    Generate a session summary via one AI call and save it with rotation.
    Returns True on success, False if skipped (empty session) or failed.
    Must be called from a background thread.
    """
    if not state.session.messages:
        return False

    from chaosz.config import build_system_prompt
    from chaosz.providers import get_client, get_native_ollama_client

    filtered = app._filter_messages_for_summary(state.session.messages)
    if not filtered:
        return False

    summary_prompt = (
        "Summarize this session as a JSON object with exactly these keys: "
        "summary (string, max 150 words), "
        "key_decisions (list of strings), "
        "unresolved_issues (list of strings). "
        "Return ONLY valid JSON, no markdown fences, no other text."
    )
    api_messages = [
        {"role": "system", "content": build_system_prompt()},
        *filtered,
        {"role": "user", "content": summary_prompt},
    ]

    try:
        if state.provider.active == "ollama":
            ollama_client = get_native_ollama_client()
            response = ollama_client.chat(
                model=state.provider.model,
                messages=api_messages,
                stream=False,
            )
            raw = response.get("message", {}).get("content", "").strip()
        else:
            client = get_client()
            params = build_api_params(
                state.provider.active,
                state.provider.model,
                api_messages,
                stream=False,
            )
            params["timeout"] = 15
            response = client.chat.completions.create(**params)
            raw = response.choices[0].message.content.strip()

        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
        data = json.loads(raw)
        summary = str(data.get("summary", ""))
        key_decisions = list(data.get("key_decisions", []))
        unresolved_issues = list(data.get("unresolved_issues", []))
    except Exception:
        return False

    files_touched = list({e["path"] for e in state.workspace.file_op_log if e.get("path")})

    session_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "active_project": state.workspace.working_dir,
        "summary": summary,
        "key_decisions": key_decisions,
        "files_touched": files_touched,
        "unresolved_issues": unresolved_issues,
    }

    try:
        _ensure_dirs()
        _rotate_sessions()
        with open(_session_path(1), "w") as f:
            json.dump(session_data, f, indent=2)
        _prune_archive()
        return True
    except Exception:
        return False
