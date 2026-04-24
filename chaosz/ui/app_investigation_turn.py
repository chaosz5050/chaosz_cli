from __future__ import annotations

import json
import os
import re
import threading

from openai import APIError, AuthenticationError, RateLimitError
from rich.text import Text

from chaosz.config import build_system_prompt, process_memory_tags
from chaosz.providers import build_api_params, get_client, get_native_ollama_client
from chaosz.session import append_to_live_session
from chaosz.state import state
from chaosz.stream_adapters import ToolCall, stream as _stream
from chaosz.tools import FILE_TOOLS, TOOL_EXECUTORS, tool_file_read
from chaosz.ui.stream_utils import unescape_tool_delta

MAX_TREE_ENTRIES = 400
MAX_TREE_DEPTH = 4
MAX_SELECTED_FILES = 16
MAX_CONTEXT_CHARS = 140_000
MAX_SELECTION_RESPONSE_CHARS = 40_000

SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "archive",
    "context",
    "logs",
}


def _record_usage(response) -> None:
    if isinstance(response, dict):
        prompt_tokens = response.get("prompt_eval_count", 0)
        completion_tokens = response.get("eval_count", 0)
        cached_tokens = 0  # Ollama doesn't report cached tokens separately in this field
    else:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(details, "cached_tokens", 0) if details else 0
    
    state.session.prompt_tokens += prompt_tokens
    state.session.completion_tokens += completion_tokens
    state.session.cached_tokens += cached_tokens
    state.session.tokens += prompt_tokens + completion_tokens


def _persist_and_render(app, text: str, *, style: str | None = None) -> None:
    cleaned = (text or "").strip()
    if not cleaned:
        cleaned = "Investigation finished with no output."
    if style:
        app.call_from_thread(app._write, "", Text(cleaned, style=style))
    else:
        app.call_from_thread(app._write_ai_turn, cleaned)
        state.session.messages.append({"role": "assistant", "content": cleaned})
        append_to_live_session("assistant", cleaned)


def _build_tree_snapshot(root: str) -> str:
    lines: list[str] = ["./"]
    count = 1
    root = os.path.realpath(root)

    for current_root, dirs, files in os.walk(root, topdown=True):
        rel_dir = os.path.relpath(current_root, root)
        if rel_dir == ".":
            depth = 0
        else:
            depth = rel_dir.count(os.sep) + 1

        dirs[:] = [d for d in sorted(dirs) if d not in SKIP_DIRS and not d.startswith(".")]
        files = [f for f in sorted(files) if not f.startswith(".")]

        if depth >= MAX_TREE_DEPTH:
            dirs[:] = []

        if rel_dir != ".":
            indent = "  " * depth
            lines.append(f"{indent}{os.path.basename(current_root)}/")
            count += 1
            if count >= MAX_TREE_ENTRIES:
                lines.append("... [tree truncated]")
                break

        for fname in files:
            indent = "  " * (depth + 1)
            lines.append(f"{indent}{fname}")
            count += 1
            if count >= MAX_TREE_ENTRIES:
                lines.append("... [tree truncated]")
                return "\n".join(lines)

    return "\n".join(lines)


def _strip_json_fences(raw: str) -> str:
    return re.sub(r'^```(?:json)?\s*|\s*```$', '', (raw or "").strip())


def _parse_file_selection(raw: str, root: str) -> tuple[list[dict], str | None]:
    payload = _strip_json_fences(raw)
    if len(payload) > MAX_SELECTION_RESPONSE_CHARS:
        payload = payload[:MAX_SELECTION_RESPONSE_CHARS]

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return [], "Selection model returned invalid JSON."

    items = data.get("files") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return [], "Selection model response missing 'files' list."

    selected: list[dict] = []
    seen: set[tuple[str, int, int | None]] = set()

    for item in items:
        if not isinstance(item, dict):
            continue
        rel_path = item.get("path")
        if not isinstance(rel_path, str) or not rel_path.strip():
            continue

        norm_rel = os.path.normpath(rel_path.strip()).replace("\\", "/")
        if norm_rel.startswith("../") or norm_rel == ".." or os.path.isabs(norm_rel):
            continue

        abs_path = os.path.realpath(os.path.join(root, norm_rel))
        if abs_path != root and not abs_path.startswith(root + os.sep):
            continue
        if not os.path.isfile(abs_path):
            continue

        start_line = item.get("start_line", 0)
        end_line = item.get("end_line")
        try:
            start_line = int(start_line)
        except (TypeError, ValueError):
            start_line = 0
        if start_line < 0:
            start_line = 0
        if end_line is not None:
            try:
                end_line = int(end_line)
            except (TypeError, ValueError):
                end_line = None
        if end_line is not None and end_line <= start_line:
            end_line = None

        key = (norm_rel, start_line, end_line)
        if key in seen:
            continue
        seen.add(key)
        selected.append({"path": norm_rel, "start_line": start_line, "end_line": end_line})

        if len(selected) >= MAX_SELECTED_FILES:
            break

    if not selected:
        return [], "Selection produced no readable files in the working directory."
    return selected, None


def _build_context_bundle(selections: list[dict]) -> tuple[str, list[str]]:
    chunks: list[str] = []
    used: list[str] = []
    total_chars = 0

    for sel in selections:
        args = {"path": sel["path"], "start_line": sel["start_line"]}
        if sel["end_line"] is not None:
            args["end_line"] = sel["end_line"]

        status, content = tool_file_read(args)
        if status != "ok":
            content = f"Error reading file: {content}"

        range_label = f"{sel['start_line']}:{sel['end_line']}" if sel["end_line"] is not None else f"{sel['start_line']}:"
        section = (
            f"FILE: {sel['path']}\n"
            f"RANGE: {range_label}\n"
            f"CONTENT:\n{content}\n"
            "-----"
        )

        if total_chars + len(section) > MAX_CONTEXT_CHARS:
            chunks.append("[CONTEXT TRUNCATED: bundle size limit reached]")
            break

        chunks.append(section)
        used.append(sel["path"])
        total_chars += len(section)

    return "\n".join(chunks), used


def run_investigation_turn(app, user_input: str) -> None:
    def _thread() -> None:
        state.ui.is_thinking = True
        app.call_from_thread(app._start_glitch)
        app.call_from_thread(app._update_footer)

        try:
            if not state.workspace.working_dir:
                _persist_and_render(
                    app,
                    "Investigation mode requires a working directory. Set one first and retry.",
                    style="yellow",
                )
                return

            root = os.path.realpath(state.workspace.working_dir)
            if not os.path.isdir(root):
                _persist_and_render(
                    app,
                    f"Working directory is invalid: {root}",
                    style="red",
                )
                return

            # Compact state.session.messages if context is large before running investigation
            _check_msgs = [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)
            app._check_and_compact_if_needed(_check_msgs)

            app.call_from_thread(app._set_status, "Investigation: building project snapshot")
            tree_snapshot = _build_tree_snapshot(root)

            client = get_client()

            app.call_from_thread(app._set_status, "Investigation: selecting relevant files")
            selection_system = (
                "You select relevant files for codebase investigation. "
                "Return JSON only, with this shape: "
                "{\"files\": [{\"path\": \"relative/path.py\", \"start_line\": 0, \"end_line\": 200}]}. "
                "Choose the smallest useful set. Use only files from the provided tree."
            )
            selection_user = (
                f"User request:\n{user_input}\n\n"
                f"Working directory: {root}\n"
                f"Project tree snapshot:\n{tree_snapshot}\n\n"
                f"Select up to {MAX_SELECTED_FILES} files."
            )

            if state.provider.active == "ollama":
                ollama_client = get_native_ollama_client()
                selection_resp = ollama_client.chat(
                    model=state.provider.model,
                    messages=[
                        {"role": "system", "content": selection_system},
                        {"role": "user", "content": selection_user},
                    ],
                    stream=False,
                )
                _record_usage(selection_resp)
                selection_text = (selection_resp.get("message", {}).get("content", "")).strip()
            else:
                selection_params = build_api_params(
                    state.provider.active,
                    state.provider.model,
                    [
                        {"role": "system", "content": selection_system},
                        {"role": "user", "content": selection_user},
                    ],
                )
                selection_params["stream"] = False
                selection_params["timeout"] = 45
                selection_resp = client.chat.completions.create(**selection_params)
                _record_usage(selection_resp)
                selection_text = (selection_resp.choices[0].message.content or "").strip()

            selections, selection_err = _parse_file_selection(selection_text, root)
            if selection_err:
                _persist_and_render(app, f"Investigation failed during file selection: {selection_err}", style="yellow")
                return

            app.call_from_thread(app._set_status, "Investigation: reading selected files")
            bundle, used_paths = _build_context_bundle(selections)
            if not used_paths:
                _persist_and_render(
                    app,
                    "Investigation failed: no selected files could be read.",
                    style="yellow",
                )
                return

            app.call_from_thread(app._set_status, "Investigation: generating analysis")
            analysis_system = (
                "You are a code investigation assistant. "
                "Answer using only the provided context. "
                "Web search is available if you need supplemental current information. "
                "Be explicit about findings, likely causes, and uncertainty."
            )
            analysis_user = (
                f"User request:\n{user_input}\n\n"
                f"Working directory: {root}\n"
                f"Selected files ({len(used_paths)}):\n" + "\n".join(f"- {p}" for p in used_paths) + "\n\n"
                f"Project tree snapshot:\n{tree_snapshot}\n\n"
                f"File context bundle:\n{bundle}"
            )

            recent_ctx = list(state.session.messages)[-6:] if state.session.messages else []
            analysis_msgs = [
                {"role": "system", "content": analysis_system},
                *recent_ctx,
                {"role": "user", "content": analysis_user},
            ]
            final_text = ""
            MAX_TOOL_LOOPS = 10

            for _loop_iter in range(MAX_TOOL_LOOPS):
                tools = FILE_TOOLS

                tool_calls_received: list[ToolCall] = []
                full_response = ""
                reasoning_started = False
                
                tool_delta_buffer = ""
                tool_line_buffer = ""
                active_tool_id = None

                for chunk in _stream(analysis_msgs, tools, state.provider.model):
                    if chunk.reasoning_line:
                        if not reasoning_started:
                            app.call_from_thread(app._start_reasoning_block)
                            reasoning_started = True
                        app.call_from_thread(app._append_reasoning_line, chunk.reasoning_line)
                    if chunk.reasoning_block:
                        app.call_from_thread(app._write_reasoning_block, chunk.reasoning_block)
                    if chunk.text:
                        full_response += chunk.text
                    if chunk.tool_delta:
                        if chunk.tool_id != active_tool_id:
                            # Start of a new tool stream (or very first one)
                            active_tool_id = chunk.tool_id
                            tool_delta_buffer = ""
                            tool_line_buffer = ""
                            app.call_from_thread(app._write, "", Text(f"▶ streaming {chunk.tool_name}...", style="dim green"))
                        
                        # Process delta
                        decoded, tool_delta_buffer = unescape_tool_delta(chunk.tool_delta, tool_delta_buffer)
                        tool_line_buffer += decoded
                        
                        # Stream lines to UI
                        if "\n" in tool_line_buffer:
                            lines = tool_line_buffer.split("\n")
                            # Write all complete lines
                            for line in lines[:-1]:
                                if line.strip():
                                    app.call_from_thread(app._write, "", Text(f"  {line}", style="dim cyan"))
                            # Keep partial line
                            tool_line_buffer = lines[-1]

                    if chunk.tool_calls:
                        # Clear any remaining line buffer at the end of tool call streaming
                        if tool_line_buffer.strip():
                            app.call_from_thread(app._write, "", Text(f"  {tool_line_buffer}", style="dim cyan"))
                        tool_line_buffer = ""
                        tool_calls_received = chunk.tool_calls
                    if chunk.usage:
                        state.session.prompt_tokens += chunk.usage["prompt"]
                        state.session.completion_tokens += chunk.usage["completion"]
                        state.session.cached_tokens += chunk.usage.get("cached", 0)
                        state.session.tokens += chunk.usage["prompt"] + chunk.usage["completion"]

                if reasoning_started:
                    app.call_from_thread(app._end_reasoning_block)

                if full_response.strip():
                    final_text = full_response

                if not tool_calls_received:
                    break

                # Build structured tool call list from adapter output
                tool_calls_for_msg = []
                tool_calls_parsed = []
                for tc in tool_calls_received:
                    tool_calls_for_msg.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": tc.arguments},
                    })
                    try:
                        parsed_args = json.loads(tc.arguments)
                    except json.JSONDecodeError:
                        parsed_args = {}
                    tool_calls_parsed.append({
                        "tool_call_id": tc.id,
                        "function_name": tc.name,
                        "args": parsed_args,
                    })

                analysis_msgs.append({
                    "role": "assistant",
                    "content": full_response or None,
                    "tool_calls": tool_calls_for_msg,
                })

                tool_result_msgs = []
                for tc in tool_calls_parsed:
                    fname = tc["function_name"]
                    tc_args = tc["args"]
                    if fname == "web_search":
                        log_status, result_content = TOOL_EXECUTORS["web_search"](tc_args)
                        path_display = tc_args.get("query", "?")
                        app.call_from_thread(app._write, "", Text(f"  [search] {path_display}", style="dim cyan"))
                    else:
                        result_content = f"Tool '{fname}' is not available in investigation mode."
                    tool_result_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["tool_call_id"],
                        "content": result_content,
                    })

                analysis_msgs.extend(tool_result_msgs)

            _persist_and_render(app, process_memory_tags(final_text))

        except AuthenticationError:
            _persist_and_render(app, f"Authentication failed. Check your API key for '{state.provider.active}'.", style="bold red")
        except RateLimitError:
            _persist_and_render(app, "Rate limit exceeded. Please wait before retrying investigation.", style="bold red")
        except APIError as e:
            _persist_and_render(app, f"API error during investigation: {e}", style="bold red")
        except Exception as e:
            _persist_and_render(app, f"Investigation error: {e}", style="bold red")
        finally:
            state.ui.is_thinking = False
            app.call_from_thread(app._stop_glitch)
            app.call_from_thread(app._set_input_label, "You: ")
            app.call_from_thread(app._update_footer)
            app.call_from_thread(lambda: app.query_one("#user-input").focus())

    threading.Thread(target=_thread, daemon=True).start()
