# Chaosz CLI

[![Version](https://img.shields.io/badge/version-0.9.4--beta-00ccaa?style=flat-square)](https://github.com/chaosz5050/chaosz_cli)
[![License](https://img.shields.io/badge/license-Source%20Available-orange?style=flat-square)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey?style=flat-square&logo=linux&logoColor=white)](https://github.com/chaosz5050/chaosz_cli)
[![Python](https://img.shields.io/badge/python-3.11%2B-3572A5?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![TUI](https://img.shields.io/badge/TUI-Textual-6E40C9?style=flat-square)](https://textual.textualize.io)

A terminal AI chat application for Linux, built with Python and [Textual](https://textual.textualize.io/). Connects to cloud AI providers (DeepSeek, Kimi, Gemini, Mistral) and local models via Ollama.

> **Plug in a brain. Own the chaos.**

## Features

- **TUI interface** — full-screen terminal UI with scrollable chat, status bar, and input history (↑/↓)
- **Streaming responses** — token-by-token output with markdown and syntax-highlighted code blocks
- **Live tool streaming** — watch code being written in real-time with matrix-style line-by-line scrolling
- **Dynamic model selection** — fetch and switch between model versions (e.g., Gemini Pro vs Flash, local Ollama tags) via `/model list`; after choosing a model, a temperature sub-menu appears to the right with 5 presets (Coding/Tools → Wild); selection is saved per-provider
- **Adaptive Ollama runtime** — inspect local model metadata and use safe runtime context/output budgets instead of blindly loading the advertised maximum; Chaosz also reloads a runner when its active context conflicts with the selected profile
- **Multi-provider** — switch between DeepSeek, Kimi, Gemini, Mistral, and Ollama at runtime; add/remove providers via an interactive menu
- **Agentic file operations** — AI can read, write, edit, rename, and delete files; all destructive ops require explicit permission
- **Verification gate** — after source-code changes, Chaosz requires a meaningful test, compile, or behavioral smoke command before accepting an AI completion; failed checks receive a focused repair pass
- **Shell execution** — AI can run terminal commands; each command requires your approval (once or session-wide)
- **Web search** — AI can search the web via DuckDuckGo for current information, recent events, and documentation
- **MCP support** — connect Model Context Protocol servers (stdio or SSE) to extend the AI with custom tools and context; managed via `/mcp`
- **Persistent memory** — AI saves facts across sessions using `[REMEMBER: category: text]` tags; included in every system prompt
- **Opt-in reflection** — consolidate memory and create a rolling session summary when exiting, without competing with an active local model during agent work
- **Prompt caching** — automatic cost reduction for DeepSeek and Kimi via session-aware caching
- **Skill system** — standards-based Agent Skills: manually select a task-mode overlay or let Chaosz load up to two confident, complementary matches for the current task. Repository-managed defaults live in `skills/<name>/SKILL.md` and are synchronized by `./setup.sh`; local custom skills live in `~/.config/chaosz/skills/`.
- **Reasoning mode** — toggle extended reasoning output with `/reason on` when supported by the active provider/model (DeepSeek, Kimi, and thinking-capable Ollama models)
- **Personality** — set a custom AI personality that persists across sessions
- **Context compaction** — `/compact` summarizes conversation history to free up context window space; auto-triggers at 90%
- **Themes** — built-in color themes (default, amber, mono, green); switch live with `/theme`; drop a custom `.theme` file in `~/.config/chaosz/themes/` to add your own
- **Project context** — drop a `chaosz.md` file in your project root and its contents are automatically injected into every system prompt as project-specific context


<img width="1247" height="956" alt="image" src="https://github.com/user-attachments/assets/d09d2104-196a-430a-874a-1448ba2f3717" />



## Limitations & Best Practices

Cloud models remain the fastest route to consistently high-quality autonomous work, but **modern local Ollama models can now complete real multi-step coding and tool-use tasks in Chaosz**. Chaosz profiles each selected Ollama model, keeps its native context maximum separate from the practical runtime context, explicitly controls supported thinking modes, recovers failed exact-match edits with a fresh read, and guides local models toward small runnable code increments. These safeguards prevent common local-agent failure modes such as enormous KV-cache allocations, repeated edits, and abandoned tool loops.

### Recommended local models

| Model | Best for | Practical trade-off |
|---|---|---|
| [`devstral:24b`](https://ollama.com/library/devstral) | Best first choice for coding agents and tool-driven repository work | ~14 GB download; text-only; still benefits from substantial CPU/GPU throughput |
| [`gemma4:12b`](https://ollama.com/library/gemma4:12b) | Best speed/capability balance for a typical laptop or desktop | ~7.6 GB; supports tools, thinking, and vision; excellent first local-agent test |
| [`qwen3.8:27b-q4_K_M`](https://ollama.com/library/qwen3.8) | Stronger broad reasoning, coding, and vision when you can tolerate slower turns | ~18 GB; a dense 27B model can be CPU-bound when it cannot fit mostly in VRAM |

Use the **Coding / Tools** temperature preset (`0.15`) for structured tool calls. Keep `/reason off` for faster execution, and turn it on only when a task genuinely needs deeper planning. Start with a contained task, let the model perform a few tool calls, and verify the result before giving it a larger refactor. Chaosz also enforces a bounded verification pass after source-code changes: the model must run a relevant test, compile check, or behavioral smoke command before its completion is accepted.

Local models are not identical to cloud frontier models: smaller or older models can still produce malformed calls, lose a plan, or confidently describe an action that did not happen. Treat tool results and files on disk as the source of truth. The permission system and automatic backups remain important guardrails.

The short version: **local agentic work is viable with a current tool-capable model and a realistic runtime profile; cloud models remain the quality and speed choice for difficult or time-sensitive work.**

## Installation

Requires **Linux**, Python 3.11+, and [uv](https://docs.astral.sh/uv/).

```bash
./run.sh
```

The script installs uv if missing, installs dependencies, and launches the app.

Or manually:

```bash
uv sync
uv run chaosz
```

## Configuration

All configuration is stored in `~/.config/chaosz/` — this directory is created automatically on first launch. It is shared across all projects.

| File | Contents |
|---|---|
| `config.json` | API keys, active provider, active model, active skill, reason flag |
| `memory.json` | Persistent AI memories across all sessions |
| `history.json` | Input history (↑/↓ navigation) |
| `themes/` | Theme files; add `.theme` JSON files here to create custom themes |
| `skills/` | Agent Skill folders (`<name>/SKILL.md`); repository-managed defaults are synchronized here by `./setup.sh`, while custom local skills are retained |
| `context/` | Rolling session snapshots (last 5 sessions) |
| `archive/` | Older sessions archived by date |
| `backups/` | Pre-edit file backups, one timestamped folder per session; auto-pruned after 7 days |
| `logs/` | Session shell logs and AI turn logs |

The **working directory** is set automatically to wherever you launch the app — no configuration needed. To give the AI project-specific context, create a `chaosz.md` file in your project root.

## Commands

| Command | Description |
|---|---|
| `/help` | Show all commands |
| `/model list` | Pick provider, then pick model version + temperature (real-time API fetch) |
| `/model add` | Interactive menu to add a new provider (`deepseek`, `kimi`, `gemini`, `ollama`) |
| `/model del <provider>` | Remove a provider |
| `/apikey` | Update API key for the current provider |
| `/reason on\|off` | Toggle reasoning output when supported by the active provider/model |
| `/context` | Choose the active Ollama model's practical runtime context window; the menu offers its native maximum and progressively smaller safe levels |
| `/personality set` | Enter a custom AI personality (multiline) |
| `/personality view` | Show current personality |
| `/personality clear` | Remove personality |
| `/memory show` | Display all saved memories |
| `/memory add <cat> <text>` | Manually add a memory |
| `/memory forget <cat> <n>` | Remove memory entry by index |
| `/memory clear` | Wipe all memories |
| `/compact` | Summarize conversation history and reset token counter |
| `/header` | Toggle the ASCII logo header on/off (preference is saved) |
| `/theme` | Interactive theme selection menu |
| `/skill list` | Interactive skill selection menu (↑/↓ navigate, Enter select, Esc cancel) |
| `/skill add <name>` | Create a new Agent Skill (multiline input; saved as `~/.config/chaosz/skills/<name>/SKILL.md`) |
| `/skill edit <name>` | Show file path for editing the skill outside the app |
| `/skill remove <name>` | Delete a skill |
| `/plan on\|off` | Toggle plan mode — AI proposes a step-by-step plan before acting; execution begins only after approval |
| `/mcp list` | Show all configured MCP servers and their connection status |
| `/mcp add` | Interactive wizard to add a new MCP server (stdio or SSE) |
| `/mcp remove <name>` | Remove an MCP server |
| `/mcp enable <name>` | Enable and connect an MCP server |
| `/mcp disable <name>` | Disable and disconnect an MCP server |
| `/stats` | Show token usage for the current session |
| `/files` | Show file operation log for this session |
| `quit` / `exit` | Exit |

## Personality vs Skills — What Goes Where

These two features look similar from the outside (both inject instructions into the AI's system prompt) but serve completely different purposes. Mixing them up leads to confusing behavior.

| | Personality | Skill |
|---|---|---|
| **Controls** | HOW the AI talks | WHAT the AI does |
| **Examples** | "Be concise", "You are a snarky senior engineer", "Respond in Dutch" | "Always read files before editing", code-review checklist, MCP conventions |
| **Scope** | Every response, regardless of task | Task-specific; automatic matches last one task, manual selection persists |
| **Cardinality** | One (global, always on) | Many exist; one manual skill or up to two automatic skills per task |
| **Storage** | `~/.config/chaosz/config.json` | `~/.config/chaosz/skills/<name>/SKILL.md` |
| **Visible in footer** | `│ ✦ persona` (dim) | `│ ✦ 1 skill` or `│ ✦ 2 skills` (highlighted) |

**Rule of thumb:** If you're describing a persona, a tone, or a communication preference — that's Personality. If you're describing a workflow, a methodology, or domain-specific rules about how to approach a category of task — that's a Skill.

**When both are active**, the AI is told explicitly: the skill governs task behavior (what to do), the personality governs tone (how to say it). They are designed to coexist. If you find them genuinely conflicting — e.g., your personality says "always explain everything in detail" but your coder skill says "be minimal" — one of them is in the wrong place.

### Agent Skills and automatic matching

Chaosz now uses the portable [Agent Skills](https://agentskills.io/specification) format. A skill is a self-contained directory, so adding, renaming, or removing a skill never requires a Chaosz code change:

```text
skills/
└── omarchy-linux-4/
    └── SKILL.md
```

The `SKILL.md` frontmatter must provide a kebab-case `name` that **exactly matches its parent folder** and a `description` that says both what the skill does and when to use it. Put specific natural task keywords in that description; Chaosz scans only this lightweight metadata before each task and loads the full instruction body only for up to two confident matches.

```yaml
---
name: omarchy-linux-4
description: Configure Omarchy Quattro, Hyprland, window rules, keybindings, and shell settings. Use for Omarchy, Hyprland, Quickshell, gaps, and monitors.
---
```

Run `./setup.sh` after changing repository skills. It safely migrates old flat `skills/<name>.md` files in `~/.config/chaosz/skills/` into folders, then synchronizes repository-managed skills. Local custom skill folders are retained.

Automatic matching is deterministic and model-independent: it compares the user request with every skill name and description—no extra model call, latency, or token spend. A manual `/skill` selection always wins until you choose `none`; otherwise up to two matched skills apply only to the current task. Their names are printed when the turn starts and the footer shows a compact count. If Chaosz cannot confidently distinguish a match, it loads no skill.

## Plan Mode

Plan mode puts the AI into a deliberate, think-before-you-act workflow. Instead of immediately executing changes, the AI first proposes a numbered step-by-step plan. During this drafting phase Chaosz withholds file, shell, and MCP tools, so the plan cannot change your workspace before you approve it in the on-screen menu.

Activate it with `/plan on`, or simply use natural language — phrases like *"make a plan for..."* or *"plan out how to..."* will trigger it automatically.

**Local model caveat:** Current tool-capable models can execute plans, but smaller or older models may still lose the thread after approval. Chaosz has a built-in step driver for Ollama: when you approve a plan, it feeds each numbered step back to the model with explicit "execute only this step" instructions. A source-changing step advances only after a terminal response and a successful relevant verification command. If it fails, Chaosz retains the step and gives the model one focused repair retry before stopping transparently. This is most effective with agentic coding models such as Devstral, Qwen3.8, and Gemma 4; use a cloud provider for the highest reliability on complex plans.

## Memory & Reflection System

The AI persists information across sessions using tagged markers in its responses:

```
[REMEMBER: category: text]
```

Valid categories: `about_user`, `preferences`, `projects`, `top_of_mind`, `workspace_context`

Tags are stripped from displayed output and written to `~/.config/chaosz/memory.json`. Memories are injected into every system prompt automatically.

The **reflection system** is offered when you exit Chaosz. It performs three key tasks:
1. **Memory Pruning:** Re-reads the current session and uses the AI to intelligently prune stale, duplicate, or misplaced memory entries.
2. **Context Learning:** Extracts architectural rules and codebase conventions into the `workspace_context` category.
3. **Session Snapshot:** Writes a concise rolling summary to the on-disk session file so that the next startup restores a lean snapshot rather than the full raw history. The live in-memory conversation is left intact — full context is preserved until the separate auto-compaction at 90% kicks in.

Keeping reflection at exit avoids a second model call competing with an active local agent for CPU, VRAM, and the Ollama runner. You'll see a subtle `░▒▓ REFLECTING ▓▒░` indicator while it is active.

Use `/memory show` to inspect memories at any time.

## MCP Servers

MCP (Model Context Protocol) servers let you extend the AI with custom tools and context blocks. Chaosz connects to them at startup and makes their tools available in the AI's tool loop alongside the built-in file/shell tools.

Both transport types are supported:
- **stdio** — local servers launched as a child process (most common)
- **SSE** — remote servers accessed via HTTP

MCP servers are configured and persisted in `~/.config/chaosz/config.json`. Use `/mcp add` to walk through the setup wizard, `/mcp list` to check connection status, and `/mcp enable`/`/mcp disable` to toggle them without removing them.

If a server exports **prompts**, those are injected into the system prompt automatically (no manual step required).

## Project Context (`chaosz.md`)

Drop a `chaosz.md` file in the root of any project you're working in:

```bash
touch chaosz.md
```

Its contents are automatically injected into the AI's system prompt every turn. Use it to give the AI persistent project-specific context — architecture decisions, naming conventions, things to never touch, current task focus. It lives alongside your code and can be committed to version control.

## Temperature

Temperature controls how deterministic or creative the model's output is. It is configured per-provider via `/model list` — after you choose a model version, a temperature sub-menu appears to the right.

| Preset | Value | Best for |
|---|---|---|
| Coding / Tools | 0.15 | Tool use, agentic tasks, structured output, code generation |
| Precise | 0.30 | Factual Q&A, summaries, technical explanations |
| Balanced | 0.70 | General chat (default) |
| Creative | 1.00 | Brainstorming, writing, idea generation |
| Wild | 1.30 | Experimental, highly varied output |

The selected temperature is saved to `~/.config/chaosz/config.json` per provider and applied to every request until changed. **For Mistral and similar instruction-tuned local models used as coding assistants, 0.15 is strongly recommended** — it eliminates the pre-execution hesitation these models exhibit at higher temperatures.

Kimi is excluded from temperature control — it rejects sampling parameters at the API level.

## Providers

| Provider | Default Model | Context | Notes |
|---|---|---|---|
| `deepseek` | deepseek-v4-flash | 128K | Supports request-level reasoning via `/reason on` |
| `kimi` | kimi-k2.5 | 256K | Supports request-level reasoning via `/reason on`; rejects sampling params |
| `gemini` | gemini-2.5-flash | 1M | Massively large context; native tool support via google-genai SDK |
| `mistral` | mistral-large-latest | 32K | OpenAI-compatible API with full tool support and temperature control |
| `ollama` | user-defined | model-dependent | Local inference; `/reason` depends on the selected model's thinking support |

## File Operations

All file tools run inside the confirmed working directory. Destructive operations (write, edit, delete, rename) require explicit `y/n` confirmation. Shell commands require `y` (once) or `s` (session) approval. The AI can also execute `sudo` commands — you'll be prompted for your password, which is cleared from memory immediately after use.

**Automatic backups:** Before any file is overwritten or deleted, Chaosz copies the original to `~/.config/chaosz/backups/<session-timestamp>/`. Each session gets its own folder named by date and time (e.g. `2026-04-24_143022`). Backup folders older than 7 days are pruned automatically on startup. This is a safety net, not a full version control system — for that, use git.

## Web Search

The AI uses DuckDuckGo search when it needs current information it can't answer from training data alone — recent events, up-to-date documentation, package versions, etc. No API key required. Results are fed back into the conversation and the AI summarizes them naturally in its response.

## License

Chaosz CLI is source-available software. You are free to use it for personal, non-commercial purposes. You may not modify it, redistribute it, or use it commercially. See [LICENSE](LICENSE) for the full terms.
