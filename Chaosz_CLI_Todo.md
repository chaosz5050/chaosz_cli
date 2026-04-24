# Chaosz CLI — Todo List

## 🔥 High Priority (Next Sessions)

- [x] Updated to DeepSeek V4 models (deepseek-v4-flash / deepseek-v4-pro). Both support tools + thinking mode. /reason on|off now just toggles the thinking API param — no model switch. reasoning_content is echoed back correctly on tool calls.

---

## 🟡 Medium Priority

### Features

- [ ] Git integration — auto-commit after file changes with descriptive messages
      — similar to how Aider handles git, users love it
      — optional: add `/export` command to dump the current conversation as Markdown or JSON (session files already exist in `~/.config/chaosz/context/`, just needs a user-facing command)
- [~] Theme system — `/theme` selector + file-based `.theme` files in `~/.config/chaosz/themes/`
      — built-ins: default (neon), amber, mono
      — **partially working:** CSS backgrounds/colors apply on switch, plasma animation themed
      — **not yet:** Rich markup colors in setup wizards (mcp/ollama), code panel borders,
        footer badges, newly mounted widgets after switch may revert to CSS defaults
      — Matrix theme can now just be a `matrix.theme` file once remaining gaps are closed
- [ ] No undo for file operations — once a `file_delete` or `file_write` is approved it's irreversible; at minimum, back up files before overwriting/deleting (git integration will eventually cover this, but a simple backup would help until then)
- [ ] Named/loadable sessions — currently every launch auto-restores the last session only; allow saving and loading named sessions so users can switch between projects without losing context
- [x] On every session Chaosz Cli writes/copies the skill directory. that should not happen! It should work fully from the project dir
- [x] Use the selection menu that is used for approving, also for permissions
- [x] Better planning. Something like a fixed space on screen, roughly 8 lines high, that shows the todo's for the project and each todo will be marked complete once it's done. That way the user has a clear vision of how far the AI is with the task. Only visible when plan mode is active via either /plan or natural language.
- [ ] Make the header collapsible if Textual supports that. I'm not sure if we can click somewhere to make it happen or require another command?

---

## 🔧 Code Quality & Architecture

### Bugs & Safety

- [x] **Functional:** Ollama context window (`state.max_ctx`) was only queried on startup — fixed; `get_model_context_window()` is now called during Ollama setup and after model switch via `/model select`
- [x] **Functional:** `session.py` — session restore on startup silently drops all `tool` role messages; AI resumes without knowing what tools ran or what they returned in the previous session
- [ ] **Functional:** `main.py` — reasoning mode state can go inconsistent: if `/reason on` is active and the user switches to a provider with no reasoning model (Kimi, Gemini, Ollama) then back, `reason_enabled` stays true but the reasoning model may not have been re-applied
- [x] **Bare except:** `commands.py` — was swallowing `KeyboardInterrupt`/`SystemExit`; changed to `except Exception`
- [x] **Tests broken after state refactor:** `tests/test_config.py` — 7 tests were patching flat attributes (`state.memory`, `state.working_dir`, `state.personality`) that moved to domain sub-objects (`state.reasoning.memory`, `state.workspace.working_dir`, `state.reasoning.personality`) during the AppState refactor; patches updated to target the correct sub-objects
- [x] I noticed that Reflection somehow deleted my name and age, so bascially all user info. It shouldn't do that of course. Why is Reflection moving that out of memory?

### Architecture & Refactoring (Future Sessions)

- [ ] `state.py` has been partially cleaned up (split into domain sub-objects: `SessionState`, `ProviderState`, `ReasoningState`, `WorkspaceState`, `PermissionsState`, `UiState`, `OllamaWizardState`, `McpWizardState`, `BackgroundState`) but `UiState` still carries plan driver state and skill menu state that arguably belong elsewhere — revisit if the class keeps growing

### Provider Scalability (medium priority, before adding providers)

- [ ] Replace `models.list()` validation in `providers.py` with a cheap chat completion call — not all providers expose `/models`
- [ ] Decouple `/model add` from `PROVIDER_REGISTRY` — allow runtime custom providers (e.g. LM Studio, any OpenAI-compat endpoint) without source edits; Ollama is already partially decoupled

---

## 🟢 Future René Problems 😄

### Big Features

- [ ] Image understanding
      — Kimi K2.5 already supports it natively (multimodal)
      — Gemini 2.5 Flash also supports images
      — relatively small addition since the API is already compatible
- [ ] Voice control / output — proof of concept first
      — Whisper for STT (local, free, runs on Legion)
      — Piper TTS for output (local, fast)
      — dependency hell warning: version conflicts everywhere
