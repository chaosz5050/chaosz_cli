import json
import os
import re
import threading
from datetime import datetime

from openai import APIError, AuthenticationError, RateLimitError
from rich.text import Text

from chaosz.config import build_system_prompt, process_memory_tags, CHAOSZ_DIR
from chaosz.shell import (
    build_shell_session_grants,
    is_always_prompt_command,
    is_command_allowed_by_session,
    tool_shell_exec,
)
from chaosz.state import _permission_event, state
from chaosz.providers import provider_requires_reasoning_echo
from chaosz.stream_adapters import ToolCall, stream as _stream
from chaosz.tools import (
    FILE_TOOLS,
    TOOL_EXECUTORS,
    _build_diff,
    _build_op_summary,
    build_file_read_session_grant,
    build_file_read_summary,
    get_all_tools,
    is_file_read_allowed_by_session,
)
from chaosz.ui.stream_utils import unescape_tool_delta

TOOL_RESULT_LOG_PATH = os.path.join(CHAOSZ_DIR, "logs", "tool_result.log")
AI_TURN_LOG_PATH = os.path.join(CHAOSZ_DIR, "logs", "ai_turn.log")
TOOL_RESULT_PREVIEW_CHARS = 500
TOOL_ARGS_SUMMARY_CHARS = 1200
AI_TURN_PREVIEW_CHARS = 500


def _summarize_tool_args(args: dict) -> tuple[str, bool]:
    try:
        summary = json.dumps(args, ensure_ascii=False, sort_keys=True)
    except Exception:
        summary = str(args)
    if len(summary) > TOOL_ARGS_SUMMARY_CHARS:
        return summary[:TOOL_ARGS_SUMMARY_CHARS] + "...", True
    return summary, False


def _write_tool_result_log_entry(
    tool_name: str,
    tool_call_id: str,
    args: dict,
    status: str,
    result_content: str,
    flags: list[str] | None = None,
    notes: str = "",
) -> None:
    os.makedirs(os.path.dirname(TOOL_RESULT_LOG_PATH), exist_ok=True)
    args_summary, args_truncated = _summarize_tool_args(args)
    preview = result_content[:TOOL_RESULT_PREVIEW_CHARS]
    flag_items = list(flags or [])
    if args_truncated:
        flag_items.append("args-summary-truncated")
    if len(result_content) > TOOL_RESULT_PREVIEW_CHARS:
        flag_items.append("preview-truncated")
    flags_text = ", ".join(flag_items) if flag_items else "-"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with open(TOOL_RESULT_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"==== TOOL RESULT @ {timestamp} ====\n")
            f.write(f"tool_name: {tool_name}\n")
            f.write(f"tool_call_id: {tool_call_id or '-'}\n")
            f.write(f"args_summary: {args_summary}\n")
            f.write(f"status: {status}\n")
            f.write(f"result_length: {len(result_content)}\n")
            f.write(f"flags: {flags_text}\n")
            f.write(f"notes: {notes or '-'}\n")
            f.write("--- preview ---\n")
            f.write(preview)
            if preview and not preview.endswith("\n"):
                f.write("\n")
            f.write("--- full_result ---\n")
            f.write(result_content)
            if result_content and not result_content.endswith("\n"):
                f.write("\n")
            f.write("==== END TOOL RESULT ====\n\n")
    except OSError:
        pass


def _estimate_api_msgs_chars(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content")
        if content:
            total += len(str(content))
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            try:
                total += len(json.dumps(tool_calls, ensure_ascii=False))
            except Exception:
                total += len(str(tool_calls))
    return total


def _write_ai_turn_iteration_log_entry(
    *,
    loop_index: int,
    provider: str,
    model: str,
    api_msgs_count: int,
    api_msgs_chars: int,
    finish_reason: str | None,
    full_response: str,
    accumulated_tool_calls_count: int,
    parsed_tool_calls_count: int,
    parsed_tool_names: list[str],
    tool_calls_made_before: bool,
    tool_calls_made_after: bool,
    recovery_nudge_injected: bool,
    branch_taken: str,
    final_iteration_decision: str,
) -> None:
    preview = full_response[:AI_TURN_PREVIEW_CHARS]
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(AI_TURN_LOG_PATH), exist_ok=True)
        with open(AI_TURN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"==== AI TURN ITERATION @ {timestamp} ====\n")
            f.write(f"loop_index: {loop_index}\n")
            f.write(f"provider: {provider}\n")
            f.write(f"model: {model}\n")
            f.write(f"api_msgs_count: {api_msgs_count}\n")
            f.write(f"api_msgs_char_estimate: {api_msgs_chars}\n")
            f.write(f"finish_reason: {finish_reason or '-'}\n")
            f.write(f"full_response_length: {len(full_response)}\n")
            f.write(f"accumulated_tool_calls_count: {accumulated_tool_calls_count}\n")
            f.write(f"parsed_tool_calls_count: {parsed_tool_calls_count}\n")
            f.write(f"parsed_tool_names: {', '.join(parsed_tool_names) if parsed_tool_names else '-'}\n")
            f.write(f"tool_calls_made_before: {'yes' if tool_calls_made_before else 'no'}\n")
            f.write(f"tool_calls_made_after: {'yes' if tool_calls_made_after else 'no'}\n")
            f.write(f"recovery_nudge_injected: {'yes' if recovery_nudge_injected else 'no'}\n")
            f.write(f"branch_taken: {branch_taken}\n")
            f.write(f"final_iteration_decision: {final_iteration_decision}\n")
            f.write("--- full_response_preview ---\n")
            f.write(preview)
            if preview and not preview.endswith("\n"):
                f.write("\n")
            f.write("==== END AI TURN ITERATION ====\n\n")
    except OSError:
        pass


def _write_ai_turn_run_outcome_log_entry(
    *,
    final_response_present: bool,
    final_response_length: int,
    tool_calls_made: bool,
    assistant_persisted: bool,
    fallback_failure_shown: bool,
    exception_summary: str = "",
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        os.makedirs(os.path.dirname(AI_TURN_LOG_PATH), exist_ok=True)
        with open(AI_TURN_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"==== AI TURN RUN OUTCOME @ {timestamp} ====\n")
            f.write(f"final_response_present: {'yes' if final_response_present else 'no'}\n")
            f.write(f"final_response_length: {final_response_length}\n")
            f.write(f"tool_calls_made: {'yes' if tool_calls_made else 'no'}\n")
            f.write(f"assistant_persisted: {'yes' if assistant_persisted else 'no'}\n")
            f.write(f"fallback_failure_shown: {'yes' if fallback_failure_shown else 'no'}\n")
            f.write(f"exception: {exception_summary or '-'}\n")
            f.write("==== END AI TURN RUN OUTCOME ====\n\n")
    except OSError:
        pass


def request_cancel() -> None:
    """Signal the running AI turn to stop at the next safe checkpoint."""
    state.ui.cancel_requested = True
    state.permissions.granted = False
    _permission_event.set()


def run_ai_turn(app) -> None:
    def _thread():
        state.ui.is_thinking = True
        show_plan_approval = False
        # Clean up any stale plan approval menu left from a previous turn
        app.call_from_thread(lambda: app.query("#plan-approval-menu").remove())
        app.call_from_thread(app._start_glitch)
        app.call_from_thread(app._update_footer)

        try:
            api_msgs = [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)
            final_response = ""
            tool_calls_made = False
            post_tool_final_retry_used = False
            seen_file_reads: dict[tuple[str, int, int | None], tuple[int, int] | None] = {}
            tool_error_counts: dict[tuple[str, str], int] = {}
            force_break = False
            assistant_persisted = False
            fallback_failure_shown = False
            prev_iter_fingerprints: frozenset | None = None

            def _resolve_read_key(args: dict) -> tuple[str, int, int | None] | None:
                if not state.workspace.working_dir:
                    return None
                rel_path = args.get("path", "")
                if not isinstance(rel_path, str) or not rel_path:
                    return None
                base = os.path.realpath(state.workspace.working_dir)
                candidate = os.path.realpath(os.path.join(base, rel_path))
                if candidate != base and not candidate.startswith(base + os.sep):
                    return None
                try:
                    start_line = int(args.get("start_line", 0))
                except (TypeError, ValueError):
                    start_line = 0
                end_line_raw = args.get("end_line")
                if end_line_raw is None:
                    end_line = None
                else:
                    try:
                        end_line = int(end_line_raw)
                    except (TypeError, ValueError):
                        end_line = None
                return candidate, start_line, end_line

            def _fingerprint_file(path: str) -> tuple[int, int] | None:
                try:
                    if not os.path.isfile(path):
                        return None
                    st = os.stat(path)
                    return st.st_mtime_ns, st.st_size
                except OSError:
                    return None

            _loop_iter = -1
            while True:
                _loop_iter += 1
                if state.ui.cancel_requested:
                    break
                tool_calls_made_before_iter = tool_calls_made
                api_msgs_count = len(api_msgs)
                api_msgs_chars = _estimate_api_msgs_chars(api_msgs)
                # Auto-compact check at start of each iteration
                api_msgs = app._check_and_compact_if_needed(api_msgs)
                tool_calls_received: list[ToolCall] = []
                full_response = ""
                finish_reason_seen: str | None = None
                reasoning_started = False
                
                reasoning_content = ""
                tool_delta_buffer = ""
                tool_line_buffer = ""
                active_tool_id = None

                tools = None if state.ui.plan_summarizing else get_all_tools()

                for chunk in _stream(api_msgs, tools, state.provider.model):
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
                            # Write all complete lines (including blank lines to preserve code structure)
                            for line in lines[:-1]:
                                app.call_from_thread(app._write, "", Text(f"  {line}", style="dim cyan"))
                            # Keep partial line
                            tool_line_buffer = lines[-1]

                    if chunk.tool_calls:
                        # Clear any remaining line buffer at the end of tool call streaming
                        if tool_line_buffer.strip():
                            app.call_from_thread(app._write, "", Text(f"  {tool_line_buffer}", style="dim cyan"))
                        tool_line_buffer = ""
                        tool_calls_received = chunk.tool_calls
                    if chunk.finish_reason:
                        finish_reason_seen = chunk.finish_reason
                    if chunk.reasoning_content:
                        reasoning_content = chunk.reasoning_content
                    if chunk.usage:
                        prompt_toks = chunk.usage.get("prompt") or 0
                        completion_toks = chunk.usage.get("completion") or 0
                        state.session.prompt_tokens += prompt_toks
                        state.session.completion_tokens += completion_toks
                        state.session.cached_tokens += chunk.usage.get("cached") or 0
                        state.session.tokens += prompt_toks + completion_toks

                    if state.ui.cancel_requested:
                        break

                if reasoning_started:
                    app.call_from_thread(app._end_reasoning_block)

                # Output token limit hit — discard partial tool calls and inject recovery hint
                if finish_reason_seen == "length":
                    app.call_from_thread(
                        app._write, "",
                        Text("⚠ Output truncated (token limit reached).", style="yellow"),
                    )
                    tool_calls_received = []
                    api_msgs.append({
                        "role": "user",
                        "content": (
                            "Your previous response was cut off because it exceeded the output token limit. "
                            "Do NOT retry writing the full file content in one call. Instead:\n"
                            "- For an existing file: use file_edit with search/replace patches\n"
                            "- For a new file: break it into logical sections, write each with separate "
                            "file_write calls, then use file_edit to connect them\n"
                            "Continue from where you were cut off using this strategy."
                        ),
                    })
                    continue

                # Display any text the AI produced this iteration
                if full_response.strip():
                    disp = process_memory_tags(full_response)
                    app.call_from_thread(app._write_ai_turn, disp.strip())
                    final_response = full_response

                # No tool calls — done (with one bounded recovery after tool-use if model returned empty text)
                if not tool_calls_received:
                    # Recovery nudge: Some models (like DeepSeek or Kimi) sometimes return 
                    # empty content after a sequence of tool calls, even though they should 
                    # provide a final summary. We inject a hidden user nudge to force a 
                    # final response if this happens exactly once per turn.
                    recovery_nudge_injected = False
                    if tool_calls_made and not full_response.strip() and not post_tool_final_retry_used:
                        api_msgs.append(
                            {
                                "role": "user",
                                "content": (
                                    "Please provide the final answer to the user now, based on the completed "
                                    "tool results above."
                                ),
                            }
                        )
                        post_tool_final_retry_used = True
                        recovery_nudge_injected = True
                        _write_ai_turn_iteration_log_entry(
                            loop_index=_loop_iter + 1,
                            provider=state.provider.active,
                            model=state.provider.model,
                            api_msgs_count=api_msgs_count,
                            api_msgs_chars=api_msgs_chars,
                            finish_reason=finish_reason_seen,
                            full_response=full_response,
                            accumulated_tool_calls_count=0,
                            parsed_tool_calls_count=0,
                            parsed_tool_names=[],
                            tool_calls_made_before=tool_calls_made_before_iter,
                            tool_calls_made_after=tool_calls_made,
                            recovery_nudge_injected=recovery_nudge_injected,
                            branch_taken="retry",
                            final_iteration_decision="continue",
                        )
                        continue
                    _write_ai_turn_iteration_log_entry(
                        loop_index=_loop_iter + 1,
                        provider=state.provider.active,
                        model=state.provider.model,
                        api_msgs_count=api_msgs_count,
                        api_msgs_chars=api_msgs_chars,
                        finish_reason=None,
                        full_response=full_response,
                        accumulated_tool_calls_count=0,
                        parsed_tool_calls_count=0,
                        parsed_tool_names=[],
                        tool_calls_made_before=tool_calls_made_before_iter,
                        tool_calls_made_after=tool_calls_made,
                        recovery_nudge_injected=recovery_nudge_injected,
                        branch_taken="break",
                        final_iteration_decision="break",
                    )
                    break

                tool_calls_made = True

                # Build structured tool call list from adapter output
                tool_calls_for_msg = []
                tool_calls_parsed = []
                for tc in tool_calls_received:
                    tool_calls_for_msg.append(
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": tc.arguments,
                            },
                        }
                    )
                    try:
                        parsed_args = json.loads(tc.arguments)
                        parse_error = None
                    except json.JSONDecodeError:
                        parsed_args = {}
                        parse_error = (
                            "Tool call arguments were truncated (the response hit the output token limit "
                            "before the JSON was complete). Break the task into smaller steps — for example, "
                            "write shorter files or split large content across multiple tool calls."
                        )
                    tool_calls_parsed.append(
                        {
                            "tool_call_id": tc.id,
                            "function_name": tc.name,
                            "args": parsed_args,
                            "parse_error": parse_error,
                        }
                    )
                parsed_tool_names = [tc["function_name"] for tc in tool_calls_parsed]

                # Some providers require reasoning_content to be echoed back on the
                # assistant tool-call turn so multi-step tool use can continue.
                assistant_msg: dict = {
                    "role": "assistant",
                    "content": full_response or None,
                    "tool_calls": tool_calls_for_msg,
                }
                if reasoning_content and state.reasoning.enabled and provider_requires_reasoning_echo(state.provider.active):
                    assistant_msg["reasoning_content"] = reasoning_content
                api_msgs.append(assistant_msg)

                # Working directory gate — fires lazily on first tool call
                if state.workspace.working_dir is None:
                    _permission_event.clear()
                    app.call_from_thread(app._prompt_working_dir)
                    _permission_event.wait()
                    if state.workspace.working_dir is None:
                        # User cancelled — feed error results and let AI respond
                        for tc in tool_calls_parsed:
                            api_msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc["tool_call_id"],
                                    "content": "Error: No working directory set. Operation cancelled.",
                                }
                            )
                        continue

                # Execute each tool call
                tool_result_msgs = []
                for tc in tool_calls_parsed:
                    fname = tc["function_name"]
                    tc_args = tc["args"]
                    executor = TOOL_EXECUTORS.get(fname)
                    entry_flags: list[str] = []
                    entry_notes = ""

                    if tc.get("parse_error"):
                        log_status = "error"
                        result_content = tc["parse_error"]
                        app.call_from_thread(
                            app._write, "",
                            Text(f"  [{fname}] failed — response was cut off (output too long)", style="red"),
                        )
                    elif fname.startswith("mcp_") and "__" in fname:
                        # MCP tool dispatch — route to the appropriate server
                        server_name = fname[len("mcp_"):].split("__")[0]
                        raw_tool_name = fname.split("__", 1)[1]
                        path_display = f"{server_name}::{raw_tool_name}"
                        summary = f"call MCP tool '{raw_tool_name}' on server '{server_name}'"

                        if fname in state.permissions.file_session_allowed:
                            from chaosz.mcp_manager import call_tool as _mcp_call
                            log_status, result_content = _mcp_call(server_name, raw_tool_name, tc_args)
                            color = "green" if log_status == "ok" else "red"
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [mcp:{server_name}] {raw_tool_name} → {result_content[:80]}", style=color),
                            )
                        else:
                            _permission_event.clear()
                            state.permissions.granted = False
                            app.call_from_thread(app._show_tool_permission_prompt, fname, summary, None)
                            _permission_event.wait()

                            if state.permissions.granted:
                                if state.permissions.file_session_granted:
                                    state.permissions.file_session_allowed.add(fname)
                                    state.permissions.file_session_granted = False
                                from chaosz.mcp_manager import call_tool as _mcp_call
                                log_status, result_content = _mcp_call(server_name, raw_tool_name, tc_args)
                            else:
                                log_status = "denied"
                                result_content = f"MCP tool '{raw_tool_name}' denied by user."

                            color = "green" if log_status == "ok" else ("yellow" if log_status == "denied" else "red")
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [mcp:{server_name}] {raw_tool_name} → {result_content[:80]}", style=color),
                            )

                        state.workspace.file_op_log.append(
                            {"op": f"mcp:{server_name}", "path": path_display, "status": log_status, "detail": result_content[:100]}
                        )
                    elif executor is None:
                        log_status = "error"
                        result_content = f"Error: unknown tool '{fname}'."
                    elif fname == "web_search":
                        # Non-destructive: execute immediately, no confirmation
                        log_status, result_content = executor(tc_args)
                        path_display = tc_args.get("query", "?")
                        app.call_from_thread(app._write, "", Text(f"  [search] {path_display}", style="dim cyan"))
                        state.workspace.file_op_log.append(
                            {"op": fname, "path": path_display, "status": log_status, "detail": ""}
                        )
                    elif fname == "file_read":
                        # Avoid exact duplicate reads in a single AI run unless file changed.
                        read_key = _resolve_read_key(tc_args)
                        should_skip = False
                        if read_key and read_key in seen_file_reads:
                            current_fp = _fingerprint_file(read_key[0])
                            if seen_file_reads[read_key] == current_fp:
                                should_skip = True

                        path_display = tc_args.get("path", "?")
                        if should_skip:
                            line_suffix = (
                                f" (lines {read_key[1]}:{read_key[2]})"
                                if read_key and (read_key[1] != 0 or read_key[2] is not None)
                                else ""
                            )
                            log_status = "ok"
                            result_content = (
                                f"Skipped duplicate file_read for '{path_display}'{line_suffix} in this run; "
                                "same path/range was already read and file is unchanged."
                            )
                            entry_flags.extend(["duplicate-skipped", "synthetic-result"])
                            entry_notes = "Duplicate read guard returned synthetic tool result without disk read."
                            app.call_from_thread(app._write, "", Text(f"  [read-skip] {path_display}", style="dim cyan"))
                            state.workspace.file_op_log.append(
                                {"op": fname, "path": path_display, "status": log_status, "detail": "duplicate-skipped"}
                            )
                        else:
                            if is_file_read_allowed_by_session(tc_args, state.permissions.file_read_session_allowed):
                                log_status, result_content = executor(tc_args)
                                if read_key:
                                    seen_file_reads[read_key] = _fingerprint_file(read_key[0])
                                app.call_from_thread(app._write, "", Text(f"  [read] {path_display} (session)", style="dim cyan"))
                            else:
                                _permission_event.clear()
                                state.permissions.granted = False
                                app.call_from_thread(app._show_tool_permission_prompt, fname, build_file_read_summary(tc_args), None)
                                _permission_event.wait()

                                if state.permissions.granted:
                                    if state.permissions.file_session_granted:
                                        grant = build_file_read_session_grant(tc_args)
                                        if grant:
                                            state.permissions.file_read_session_allowed.add(grant)
                                        state.permissions.file_session_granted = False
                                    log_status, result_content = executor(tc_args)
                                    if read_key:
                                        seen_file_reads[read_key] = _fingerprint_file(read_key[0])
                                else:
                                    log_status = "denied"
                                    result_content = f"File read '{path_display}' denied by user."

                                color = "dim cyan" if log_status == "ok" else ("yellow" if log_status == "denied" else "red")
                                app.call_from_thread(app._write, "", Text(f"  [read] {path_display} → {result_content[:80]}", style=color))
                            state.workspace.file_op_log.append(
                                {"op": fname, "path": path_display, "status": log_status, "detail": ""}
                            )
                    elif fname == "shell_exec":
                        command = tc_args.get("command", "")
                        reason = tc_args.get("reason", "")

                        # Check session memory
                        if is_command_allowed_by_session(command, state.permissions.shell_session_allowed):
                            # Execute without prompting
                            log_status, result_content = tool_shell_exec(tc_args)
                        else:
                            # Determine if always-prompt command
                            always_prompt = is_always_prompt_command(command)

                            _permission_event.clear()
                            state.permissions.granted = False
                            state.permissions.awaiting_shell = True
                            state.permissions.pending_shell_command = (command, reason, tc_args, tc["tool_call_id"])
                            app.call_from_thread(app._show_shell_permission_prompt, command, reason, always_prompt)
                            _permission_event.wait()

                            if state.permissions.granted:
                                # If session granted, add to session memory
                                if state.permissions.shell_session_granted and not always_prompt:
                                    state.permissions.shell_session_allowed.update(
                                        build_shell_session_grants(command)
                                    )

                                # Check if sudo command
                                if command.strip().startswith("sudo "):
                                    # Switch to password mode
                                    state.ui.mode = "PASSWORD"
                                    app.call_from_thread(app._prompt_sudo_password)
                                    _permission_event.clear()
                                    _permission_event.wait()
                                    # Password now in state.sudo_password
                                    log_status, result_content = tool_shell_exec(tc_args)
                                    # tool_shell_exec will clear sudo_password after use
                                else:
                                    log_status, result_content = tool_shell_exec(tc_args)
                            else:
                                log_status = "denied"
                                result_content = "Shell command denied by user."

                        # Store output summary
                        full_output = result_content  # store before any truncation
                        state.workspace.file_op_log.append(
                            {
                                "op": fname,
                                "path": command,
                                "status": log_status,
                                "detail": full_output[:100],  # truncated for log
                            }
                        )
                        # Keep original full output for AI (tool result)
                        result_content = full_output
                        # Compute display properties
                        lines = full_output.split("\n")
                        line_count = len(lines)
                        is_error = log_status != "ok"
                        # Display summary line
                        log_filename = os.path.basename(state.session.log_path) if state.session.log_path else "session1.log"
                        prefix = "▶ shell error" if is_error else "▶ shell output"
                        color = "red" if is_error else "dim cyan"
                        summary = f"  {prefix} ({line_count} lines) — saved to logs/{log_filename}"
                        app.call_from_thread(app._write, "", Text(summary, style=color))
                    else:
                        # Destructive file operations: requires user confirmation (or session bypass)
                        diff_text = _build_diff(tc_args) if fname == "file_edit" else None
                        summary = _build_op_summary(fname, tc_args)
                        path_display = tc_args.get("path") or tc_args.get("old_path") or tc_args.get("filename") or tc_args.get("file", "?")

                        if fname in state.permissions.file_session_allowed:
                            log_status, result_content = executor(tc_args)
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [{fname}] {path_display} → {result_content} (session)", style="green"),
                            )
                        else:
                            _permission_event.clear()
                            state.permissions.granted = False
                            app.call_from_thread(app._show_tool_permission_prompt, fname, summary, diff_text)
                            _permission_event.wait()

                            if state.permissions.granted:
                                if state.permissions.file_session_granted:
                                    state.permissions.file_session_allowed.add(fname)
                                    state.permissions.file_session_granted = False
                                log_status, result_content = executor(tc_args)
                            else:
                                log_status = "denied"
                                result_content = f"Operation '{fname}' denied by user."

                            color = "green" if log_status == "ok" else ("yellow" if log_status == "denied" else "red")
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [{fname}] {path_display} → {result_content}", style=color),
                            )

                        state.workspace.file_op_log.append(
                            {
                                "op": fname,
                                "path": path_display,
                                "status": log_status,
                                "detail": result_content,
                            }
                        )

                    # Repeated-error guard: if the same tool+path keeps failing, stop the loop
                    if log_status == "error":
                        err_key = (fname, tc_args.get("path", tc_args.get("command", "")))
                        tool_error_counts[err_key] = tool_error_counts.get(err_key, 0) + 1
                        if tool_error_counts[err_key] >= 2:
                            result_content = (
                                (result_content if isinstance(result_content, str) else str(result_content))
                                + "\n\nNOTE: You have now received this same error multiple times for the "
                                "same operation. Do NOT retry this tool call. Stop using tools and "
                                "explain the problem to the user in plain text instead."
                            )
                            force_break = True

                    result_text = result_content if isinstance(result_content, str) else str(result_content)
                    if "[TRUNCATED:" in result_text:
                        entry_flags.append("result-truncated")
                    _write_tool_result_log_entry(
                        tool_name=fname,
                        tool_call_id=tc["tool_call_id"],
                        args=tc_args,
                        status=log_status,
                        result_content=result_text,
                        flags=entry_flags,
                        notes=entry_notes,
                    )
                    tool_result_msgs.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc["tool_call_id"],
                            "content": result_text,
                        }
                    )

                api_msgs.extend(tool_result_msgs)

                if force_break:
                    break

                # Stuck-loop guard: if this iteration made the exact same tool calls as the
                # previous one (same names + same arguments), the AI is spinning. Break.
                current_fingerprints = frozenset(
                    (tc["function_name"], json.dumps(tc["args"], sort_keys=True))
                    for tc in tool_calls_parsed
                )
                if prev_iter_fingerprints is not None and current_fingerprints == prev_iter_fingerprints:
                    app.call_from_thread(
                        app._write, "",
                        Text(
                            "⚠ Detected repeated identical tool calls — stopping to avoid an infinite loop.",
                            style="yellow",
                        ),
                    )
                    break
                prev_iter_fingerprints = current_fingerprints

                # Loop: next iteration sends tool results back to the AI
                branch_taken = "continue"
                final_decision = "continue"
                _write_ai_turn_iteration_log_entry(
                    loop_index=_loop_iter + 1,
                    provider=state.provider.active,
                    model=state.provider.model,
                    api_msgs_count=api_msgs_count,
                    api_msgs_chars=api_msgs_chars,
                    finish_reason=None,
                    full_response=full_response,
                    accumulated_tool_calls_count=len(tool_calls_received),
                    parsed_tool_calls_count=len(tool_calls_parsed),
                    parsed_tool_names=parsed_tool_names,
                    tool_calls_made_before=tool_calls_made_before_iter,
                    tool_calls_made_after=tool_calls_made,
                    recovery_nudge_injected=False,
                    branch_taken=branch_taken,
                    final_iteration_decision=final_decision,
                )

            # Persist the final text response to conversation history
            if final_response:
                state.session.messages.append({"role": "assistant", "content": final_response})
                from chaosz.session import append_to_live_session

                append_to_live_session("assistant", final_response)
                assistant_persisted = True

                # Auto-trigger reflection if enough messages have accumulated
                real_messages = [m for m in state.session.messages if m.get("role") != "reflection_summary"]
                if len(real_messages) >= 10 and not state.background.reflection_active:
                    threading.Thread(target=state.trigger_reflection, args=(app,), daemon=True).start()
            elif tool_calls_made:
                app.call_from_thread(
                    app._write,
                    "",
                    Text(
                        "● AI\nUnable to produce a final answer after completing tool calls. "
                        "The model returned no final response.",
                        style="yellow",
                    ),
                )
                fallback_failure_shown = True
            _write_ai_turn_run_outcome_log_entry(
                final_response_present=bool(final_response),
                final_response_length=len(final_response),
                tool_calls_made=tool_calls_made,
                assistant_persisted=assistant_persisted,
                fallback_failure_shown=fallback_failure_shown,
            )

        except AuthenticationError:
            _write_ai_turn_run_outcome_log_entry(
                final_response_present=False,
                final_response_length=0,
                tool_calls_made=False,
                assistant_persisted=False,
                fallback_failure_shown=False,
                exception_summary="AuthenticationError",
            )
            app.call_from_thread(
                app._write,
                "",
                Text(f"Authentication failed. Check your API key for '{state.provider.active}'.", style="bold red"),
            )
        except RateLimitError:
            _write_ai_turn_run_outcome_log_entry(
                final_response_present=False,
                final_response_length=0,
                tool_calls_made=False,
                assistant_persisted=False,
                fallback_failure_shown=False,
                exception_summary="RateLimitError",
            )
            app.call_from_thread(
                app._write,
                "",
                Text("Rate limit exceeded. Please wait before trying again.", style="bold red"),
            )
        except APIError as e:
            _write_ai_turn_run_outcome_log_entry(
                final_response_present=False,
                final_response_length=0,
                tool_calls_made=False,
                assistant_persisted=False,
                fallback_failure_shown=False,
                exception_summary=f"APIError: {e}",
            )
            error_msg = str(e)
            if "Model does not exist" in error_msg:
                app.call_from_thread(app._write, "", Text(f"Model '{state.provider.model}' not found.", style="bold red"))
            else:
                app.call_from_thread(app._write, "", Text(f"API error: {e}", style="bold red"))
        except Exception as e:
            _write_ai_turn_run_outcome_log_entry(
                final_response_present=False,
                final_response_length=0,
                tool_calls_made=False,
                assistant_persisted=False,
                fallback_failure_shown=False,
                exception_summary=f"{type(e).__name__}: {e}",
            )
            app.call_from_thread(app._write, "", Text(f"Error: {e}", style="bold red"))
        finally:
            # Capture post-turn routing inputs before resetting transient flags.
            _was_plan_summarizing = state.ui.plan_summarizing
            _was_plan_turn = state.ui.plan_mode or state.ui.plan_mode_this_turn
            if not state.ui.plan_executing and not _was_plan_summarizing and _was_plan_turn:
                _last_user = next(
                    (m.get("content", "") for m in reversed(state.session.messages) if m.get("role") == "user"),
                    "",
                )
                if not _last_user.startswith("All steps complete"):
                    from chaosz.plan_driver import parse_plan_steps

                    last_assistant = next(
                        (m["content"] for m in reversed(state.session.messages) if m.get("role") == "assistant"),
                        "",
                    )
                    steps = parse_plan_steps(last_assistant)
                    if steps:
                        state.ui.plan_steps = steps
                        state.ui.plan_goal = _last_user
                        state.ui.plan_mode = True  # promote to persistent so Discuss turns keep plan context
                        show_plan_approval = True

            state.ui.is_thinking = False
            state.ui.cancel_requested = False
            state.ui.plan_summarizing = False
            state.ui.plan_mode_this_turn = False
            app.call_from_thread(app._stop_glitch)
            app.call_from_thread(app._set_input_label, "You: ")
            app.call_from_thread(app._update_footer)

            if state.ui.plan_executing:
                next_index = state.ui.plan_step_index + 1
                if next_index < len(state.ui.plan_steps):
                    from chaosz.plan_driver import build_step_prompt
                    from chaosz.session import append_to_live_session
                    state.ui.plan_step_index = next_index
                    next_prompt = build_step_prompt(next_index, state.ui.plan_steps, state.ui.plan_goal)
                    total = len(state.ui.plan_steps)
                    app.call_from_thread(
                        app._write, "",
                        Text(f"▶ Step {next_index + 1}/{total}", style="dim cyan")
                    )
                    state.session.messages.append({"role": "user", "content": next_prompt})
                    append_to_live_session("user", next_prompt)
                    app.call_from_thread(app._run_routed_turn, next_prompt)
                else:
                    # All steps done — run a dedicated summary turn instead of stopping silently
                    state.ui.plan_executing = False
                    state.ui.plan_step_index = 0
                    state.ui.plan_steps = []
                    state.ui.plan_goal = ""
                    state.ui.plan_mode = False        # belt-and-suspenders: ensures _was_plan_turn=False in summary turn
                    state.ui.plan_summarizing = True
                    from chaosz.session import append_to_live_session
                    summary_msg = "All steps complete. Describe what you did."
                    state.session.messages.append({"role": "user", "content": summary_msg})
                    append_to_live_session("user", summary_msg)
                    app.call_from_thread(
                        app._write, "",
                        Text("✓ All steps complete.", style="bold green")
                    )
                    app.call_from_thread(app._run_ai_turn)  # run_ai_turn takes only app; msg already in state
            elif show_plan_approval:
                app.call_from_thread(app._render_plan_approval_menu)
                app.call_from_thread(lambda: setattr(state.ui, "mode", "PLAN_APPROVE"))
                app.call_from_thread(lambda: app.query_one("#user-input").focus())
            else:
                app.call_from_thread(lambda: app.query_one("#user-input").focus())

    threading.Thread(target=_thread, daemon=True).start()
