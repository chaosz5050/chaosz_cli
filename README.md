# Chaosz CLI

[![Version](https://img.shields.io/badge/version-0.8.1-00ccaa?style=flat-square)](https://github.com/chaosz5050/chaosz_cli)
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
- **Multi-provider** — switch between DeepSeek, Kimi, Gemini, Mistral, and Ollama at runtime; add/remove providers via an interactive menu
- **Agentic file operations** — AI can read, write, edit, rename, and delete files; all destructive ops require explicit permission
- **Shell execution** — AI can run terminal commands; each command requires your approval (once or session-wide)
- **Web search** — AI can search the web via DuckDuckGo for current information, recent events, and documentation
- **MCP support** — connect Model Context Protocol servers (stdio or SSE) to extend the AI with custom tools and context; managed via `/mcp`
- **Persistent memory** — AI saves facts across sessions using `[REMEMBER: category: text]` tags; included in every system prompt
- **Reflection system** — AI automatically consolidates and prunes its memory after every 10 messages in the background, keeping context lean and retaining task flow via rolling summaries
- **Prompt caching** — automatic cost reduction for DeepSeek and Kimi via session-aware caching
- **Skill system** — activate on-demand task-mode overlays (coder, code-review, mcp-builder, or your own); stored as plain `.md` files in `~/.config/chaosz/skills/` so you can edit them at any time
- **Reasoning mode** — toggle extended reasoning output with `/reason on` when supported by the active provider/model (DeepSeek, Kimi, and thinking-capable Ollama models)
- **Personality** — set a custom AI personality that persists across sessions
- **Context compaction** — `/compact` summarizes conversation history to free up context window space; auto-triggers at 90%
- **Themes** — built-in color themes (default, amber, mono, green); switch live with `/theme`; drop a custom `.theme` file in `~/.config/chaosz/themes/` to add your own
- **Project context** — drop a `chaosz.md` file in your project root and its contents are automatically injected into every system prompt as project-specific context

## Limitations & Best Practices

While Chaosz CLI supports both local and cloud models, **your experience will vary significantly based on the intelligence and training of the active model.**

> ⚠️ **Local Ollama models are not recommended for agentic use.** They will hallucinate tool calls, fabricate file operations, and describe actions they never actually execute. This is a fundamental model capability issue — not a bug in Chaosz CLI. If you want the full capacity of Chaosz CLI (reliable tool use, plan execution, multi-step agentic tasks), hook it up with a proper API model: **Kimi, DeepSeek, or Gemini**.

**Cloud APIs (Gemini, DeepSeek, Kimi) are recommended for real work.** These models have been explicitly fine-tuned for high-reliability function calling. They natively understand the file operation tools, respect the sandbox boundaries, and can orchestrate complex, multi-file refactors autonomously with minimal prompting.

**Local Models (Ollama) are a different story.** Most local models — even reasonably capable ones like Gemma or Llama — were not fine-tuned for reliable tool use. What you can expect:

- **Tool calls are unreliable.** Smaller local models frequently forget they have tools available, output malformed JSON, or describe what they *would* do instead of calling the tool. If this happens, be explicit in your prompt: *"Use the `file_write` tool to save this code"*.
- **Hallucinated actions.** A local model may confidently tell you it wrote a file, edited a function, or ran a command — and then have done none of those things. Always verify the actual result.
- **Plan mode may not execute.** A common failure: the model writes a reasonable plan, you approve it, and then asks you to re-explain the task from scratch — completely forgetting what it planned. Chaosz has a step driver that attempts to work around this by feeding each plan step back to the model one at a time, but even this is not foolproof with weaker models.
- **Multi-step agentic tasks are not reliable.** Chaining more than 2-3 tool calls in a single turn requires the model to maintain context across intermediate results. Most local models lose the thread.

**Best local model:** If you do use Ollama, `mistral-small3.2:latest` at temperature `0.15` (Coding / Tools preset) gives the most consistent results — it follows tool call format better than most alternatives and its low temperature reduces the pre-execution hesitation that plagues instruction-tuned models at higher settings. That said, it will still hallucinate actions. Treat its output as a draft, not ground truth.

The short version: **Ollama is fine for chatting and quick questions. For anything involving planning, tool use, or autonomous execution, use a cloud provider.**

## Installation

Requires **Linux**, Python 3.11+, and [Poetry](https://python-poetry.org/).

```bash
./run.sh
```

The script installs Poetry if missing, installs dependencies, and launches the app.

Or manually:

```bash
poetry install
poetry run chaosz
```

## Configuration

All configuration is stored in `~/.config/chaosz/` — this directory is created automatically on first launch. It is shared across all projects.

| File | Contents |
|---|---|
| `config.json` | API keys, active provider, active model, active skill, reason flag |
| `memory.json` | Persistent AI memories across all sessions |
| `history.json` | Input history (↑/↓ navigation) |
| `themes/` | Theme files; add `.theme` JSON files here to create custom themes |
| `skills/` | Skill overlay files; add `.md` files here to create custom skills |
| `context/` | Rolling session snapshots (last 5 sessions) |
| `archive/` | Older sessions archived by date |
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
| `/skill add <name>` | Create a new skill (multiline input; saved as `~/.config/chaosz/skills/<name>.md`) |
| `/skill edit <name>` | Show file path for editing the skill outside the app |
| `/skill remove <name>` | Delete a skill |
| `/plan on\|off` | Toggle plan mode — AI proposes a step-by-step plan before acting |
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
| **Scope** | Every response, regardless of task | Task-specific; only active when selected |
| **Cardinality** | One (global, always on) | Many exist, one active at a time |
| **Storage** | `~/.config/chaosz/config.json` | `~/.config/chaosz/skills/<name>.md` |
| **Visible in footer** | `│ ✦ persona` (dim) | `│ skill-name` (highlighted) |

**Rule of thumb:** If you're describing a persona, a tone, or a communication preference — that's Personality. If you're describing a workflow, a methodology, or domain-specific rules about how to approach a category of task — that's a Skill.

**When both are active**, the AI is told explicitly: the skill governs task behavior (what to do), the personality governs tone (how to say it). They are designed to coexist. If you find them genuinely conflicting — e.g., your personality says "always explain everything in detail" but your coder skill says "be minimal" — one of them is in the wrong place.

## Plan Mode

Plan mode puts the AI into a deliberate, think-before-you-act workflow. Instead of immediately executing changes, the AI first reasons through the problem and proposes a numbered step-by-step plan. You review it, then say *"execute"* (or *"go ahead"*) to proceed.

Activate it with `/plan on`, or simply use natural language — phrases like *"make a plan for..."* or *"plan out how to..."* will trigger it automatically.

**Local model caveat:** Smaller Ollama models are generally not suited for plan mode. The model may produce a reasonable plan but then fail to follow through when asked to execute. A common failure pattern: the model writes a plan, asks "does this look good?", receives approval — and then completely forgets what it was going to do, asking you to re-explain the task from scratch. This is a model capability issue, not a bug.

Chaosz has a built-in step driver for Ollama: when you approve a plan, it feeds each numbered step back to the model one at a time with explicit "execute only this step" instructions. This helps, but even then a poorly trained model may still lose the thread. For plan mode to work reliably, use a cloud provider (DeepSeek, Kimi, or Gemini).

## Memory & Reflection System

The AI persists information across sessions using tagged markers in its responses:

```
[REMEMBER: category: text]
```

Valid categories: `about_user`, `preferences`, `projects`, `top_of_mind`, `workspace_context`

Tags are stripped from displayed output and written to `~/.config/chaosz/memory.json`. Memories are injected into every system prompt automatically.

The **reflection system** runs automatically in the background whenever 10 messages have accumulated in the current session. It performs three key tasks:
1. **Memory Pruning:** Re-reads the current session and uses the AI to intelligently prune stale, duplicate, or misplaced memory entries.
2. **Context Learning:** Extracts architectural rules and codebase conventions into the `workspace_context` category.
3. **Session Snapshot:** Writes a concise rolling summary to the on-disk session file so that the next startup restores a lean snapshot rather than the full raw history. The live in-memory conversation is left intact — full context is preserved until the separate auto-compaction at 90% kicks in.

Reflection is entirely non-blocking; you can continue typing while it processes in the background. You'll see a subtle `░▒▓ REFLECTING ▓▒░` indicator in the status bar when it's active.

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

## Web Search

The AI uses DuckDuckGo search when it needs current information it can't answer from training data alone — recent events, up-to-date documentation, package versions, etc. No API key required. Results are fed back into the conversation and the AI summarizes them naturally in its response.

## License

Chaosz CLI is source-available software. You are free to use it for personal, non-commercial purposes. You may not modify it, redistribute it, or use it commercially. See [LICENSE](LICENSE) for the full terms.
