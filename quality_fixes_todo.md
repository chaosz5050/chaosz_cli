# Chaosz CLI — Quality Fixes Todo

Generated from code review (2026-04-15). Ordered by priority.

---

## Critical

- [x] **Sandbox path escape via prefix matching** (`chaosz/tools.py:250`)
  - `candidate.startswith(base)` passes if working dir name is a prefix of a sibling dir.
  - Example: sandbox `/home/rene/proj`, AI requests `../proj-secrets/key.txt` → resolves to `/home/rene/proj-secrets/key.txt` → startswith check passes (bug).
  - Fix:
    ```python
    # Before:
    if not candidate.startswith(base):
    # After:
    if not (candidate == base or candidate.startswith(base + os.sep)):
    ```

---

## High

- [x] **System prompt contradicts sandbox** (`chaosz/config.py:25`)
  - Prompt says: *"You may use absolute file paths to read or write files anywhere on the system."*
  - Reality: absolute paths are silently re-rooted inside the sandbox. AI gets confused when paths outside sandbox fail.
  - Fix: rewrite the relevant sentence to describe the sandbox truthfully.

- [ ] **Reflection updates `state.session.messages` outside the lock** (`chaosz/session.py:279`)
  - `state.session.lock` is held only around the file write, not the in-memory list replacement.
  - If an AI turn is concurrently reading `state.session.messages`, it can see an inconsistent mid-swap state.
  - Fix: extend the `with state.session.lock:` block to also cover the `state.session.messages = [...]` assignment.

- [ ] **`append_to_live_session` is not crash-safe** (`chaosz/session.py:96–108`)
  - Read-modify-write pattern: a crash between read and write corrupts or loses the session file.
  - Fix: write to a tempfile then `os.replace()` (atomic on Linux):
    ```python
    import tempfile
    with tempfile.NamedTemporaryFile("w", dir=CONTEXT_DIR, delete=False, suffix=".tmp") as tmp:
        json.dump(data, tmp, indent=2)
    os.replace(tmp.name, LIVE_SESSION)
    ```

---

## Medium

- [ ] **`start_line` accepts negative values in `tool_file_read`** (`chaosz/tools.py:266`)
  - Negative values work as Python list indices, allowing unintended "read from end of file" behavior.
  - Fix: `start_line = max(0, int(args.get("start_line", 0)))`

- [ ] **Reflection sends entire session to AI with no size guard** (`chaosz/session.py:168`)
  - Long sessions will exceed the reflection model's context window, causing silent failures.
  - Fix: cap `real_messages` before serializing (e.g., last 50 messages or ~50k chars).

- [ ] **`load_input_history` missing `try/except` around `open()`** (`chaosz/config.py:158–163`)
  - File exists but wrong permissions → unhandled `PermissionError`.
  - Fix: wrap the `open()` call in the same try/except used by `load_memory()`.

- [ ] **`save_memory`, `save_input_history`, `_write_config_file` have no error handling**
  - All three crash with unhandled `OSError` on full disk or permission change.
  - Fix: catch `OSError`, log it, and return gracefully.

- [ ] **No backup before file overwrite/delete**
  - A bad AI edit currently has no recovery path.
  - Fix (short-term, before git integration): `shutil.copy2(path, path + ".bak")` before `file_write` (overwrite) and `file_delete`.

- [ ] **Shell timeout (30s) is unconfigurable** (`chaosz/shell.py:116`)
  - Package installs, builds, test runs routinely exceed 30s. AI then treats them as failures.
  - Fix: make timeout configurable in `config.json`, or detect long-running command patterns and prompt the user.

- [ ] **Session restore gives AI no signal that tool history was dropped** (`chaosz/session.py:301`)
  - AI resumes mid-conversation unaware that all tool execution context is gone.
  - Fix: inject a system-style message in `restored` list: `"[Note: tool execution history from previous session is not available]"`.

---

## Low / Cosmetic

- [ ] **`apply_surgical_edit` — inline return on `if` line** (`chaosz/tools.py:391`)
  - PEP 8 violation; inconsistent with rest of file.
  - Fix: expand to two lines.

- [ ] **`config.py` has side effects at import time** (`chaosz/config.py:21`)
  - `_ensure_chaosz_dir()` runs at import, creating directories on disk. Hurts testability.
  - Fix: call it explicitly from `main.py` startup instead.

- [ ] **`build_system_prompt` is doing too much** (`chaosz/config.py:205`)
  - 60+ lines with six conditional blocks. Hard to scan.
  - Fix: extract each section into a private helper (`_personality_section()`, `_skill_section()`, `_memory_section()`, etc.). The main function becomes a readable list of `parts.extend(...)` calls.

- [ ] **Deferred imports inside `build_system_prompt`** (`chaosz/config.py:206`, `221`, `246`)
  - `from datetime import datetime` deferred unnecessarily (no circular import risk).
  - Fix: move `datetime` import to top of file. The circular import for `skills`/`mcp_manager` is worth untangling separately.

- [ ] **Permission `awaiting` flag not concurrent-safe for parallel tool calls**
  - If the model ever returns parallel tool calls, two could race on `awaiting`. Currently safe because tool calls are serialized, but this assumption is undocumented.
  - Fix: add a comment documenting the serialization assumption, or enforce it with a lock.

---

## Architecture (Non-urgent)

- [ ] **`tools.py` is getting large** — consider splitting into `tools/file.py`, `tools/shell.py`, `tools/schemas.py`.
- [ ] **`UiState` carries plan and skill-menu state** (`chaosz/state.py:61`) — consider `PlanState` and `MenuState` domain objects.
- [ ] **`state.py` global singleton makes testing harder** — mock-friendly alternative: pass `state` as a parameter to functions that need it, or use a factory function in tests.
- [ ] **`models.list()` not universal for provider validation** (TODO in `providers.py`) — replace with a cheap chat completion call.
