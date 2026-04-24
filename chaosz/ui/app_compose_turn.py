from __future__ import annotations

import json
import threading

from openai import APIError, AuthenticationError, RateLimitError
from rich.text import Text

from chaosz.config import build_system_prompt, process_memory_tags
from chaosz.session import append_to_live_session
from chaosz.shell import is_always_prompt_command, tool_shell_exec
from chaosz.state import _permission_event, state
from chaosz.stream_adapters import ToolCall, stream as _stream
from chaosz.tools import FILE_TOOLS, TOOL_EXECUTORS, _build_diff, _build_op_summary
from chaosz.ui.stream_utils import unescape_tool_delta

COMPOSE_SYSTEM_INSTRUCTION = (
    "Compose mode: produce the requested output as a complete, well-structured answer. "
    "Web search is available if you need current information. "
    "If the user asks you to write or save content to a file, use the file_write tool — "
    "do not output file contents directly to chat."
)


def run_compose_turn(app, _user_input: str) -> None:
    """
    _user_input is unused here because the message has already been appended
    to state.session.messages by the input submitted handler before routing.
    """
    def _thread() -> None:
        state.ui.is_thinking = True
        app.call_from_thread(app._start_glitch)
        app.call_from_thread(app._update_footer)

        try:
            # Compact state.session.messages if context is large before building api_msgs
            _check_msgs = [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)
            app._check_and_compact_if_needed(_check_msgs)

            api_msgs = [
                {"role": "system", "content": build_system_prompt()},
                {"role": "system", "content": COMPOSE_SYSTEM_INSTRUCTION},
            ] + list(state.session.messages)

            final_response = ""
            MAX_TOOL_LOOPS = 10

            for _loop_iter in range(MAX_TOOL_LOOPS):
                if state.ui.cancel_requested:
                    break
                tools = FILE_TOOLS

                tool_calls_received: list[ToolCall] = []
                full_response = ""
                finish_reason_seen: str | None = None
                reasoning_started = False
                
                tool_delta_buffer = ""
                tool_line_buffer = ""
                active_tool_id = None

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
                    if chunk.usage:
                        state.session.prompt_tokens += chunk.usage["prompt"]
                        state.session.completion_tokens += chunk.usage["completion"]
                        state.session.cached_tokens += chunk.usage.get("cached", 0)
                        state.session.tokens += chunk.usage["prompt"] + chunk.usage["completion"]

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

                if full_response.strip():
                    disp = process_memory_tags(full_response)
                    app.call_from_thread(app._write_ai_turn, disp.strip())
                    final_response = full_response

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
                        parse_error = None
                    except json.JSONDecodeError:
                        parsed_args = {}
                        parse_error = (
                            "Tool call arguments were truncated (the response hit the output token limit "
                            "before the JSON was complete). Break the task into smaller steps — for example, "
                            "write shorter files or split large content across multiple tool calls."
                        )
                    tool_calls_parsed.append({
                        "tool_call_id": tc.id,
                        "function_name": tc.name,
                        "args": parsed_args,
                        "parse_error": parse_error,
                    })

                api_msgs.append({
                    "role": "assistant",
                    "content": full_response or None,
                    "tool_calls": tool_calls_for_msg,
                })

                # Working directory gate — fires lazily on first tool call requiring it
                if state.workspace.working_dir is None:
                    _permission_event.clear()
                    app.call_from_thread(app._stop_glitch)
                    app.call_from_thread(app._prompt_working_dir)
                    _permission_event.wait()
                    app.call_from_thread(app._start_glitch)
                    if state.workspace.working_dir is None:
                        for tc in tool_calls_parsed:
                            api_msgs.append({
                                "role": "tool",
                                "tool_call_id": tc["tool_call_id"],
                                "content": "Error: No working directory set. Operation cancelled.",
                            })
                        continue

                tool_result_msgs = []
                for tc in tool_calls_parsed:
                    fname = tc["function_name"]
                    tc_args = tc["args"]
                    executor = TOOL_EXECUTORS.get(fname)

                    if tc.get("parse_error"):
                        result_content = tc["parse_error"]
                        app.call_from_thread(
                            app._write, "",
                            Text(f"  [{fname}] failed — response was cut off (output too long)", style="red"),
                        )
                    elif executor is None:
                        result_content = f"Error: unknown tool '{fname}'."
                    elif fname == "web_search":
                        # Non-destructive: execute immediately, no confirmation
                        _log_status, result_content = executor(tc_args)
                        path_display = tc_args.get("query", "?")
                        app.call_from_thread(app._write, "", Text(f"  [search] {path_display}", style="dim cyan"))
                    elif fname == "file_read":
                        # Non-destructive: execute immediately, no confirmation
                        _log_status, result_content = executor(tc_args)
                        path_display = tc_args.get("path", "?")
                        app.call_from_thread(app._write, "", Text(f"  [read] {path_display}", style="dim cyan"))
                    elif fname == "shell_exec":
                        command = tc_args.get("command", "")
                        reason = tc_args.get("reason", "")
                        _log_status = "ok"

                        if command in state.permissions.shell_session_allowed:
                            _log_status, result_content = tool_shell_exec(tc_args)
                        else:
                            always_prompt = is_always_prompt_command(command)
                            _permission_event.clear()
                            state.permissions.granted = False
                            state.permissions.awaiting_shell = True
                            state.permissions.pending_shell_command = (command, reason, tc_args, tc["tool_call_id"])
                            app.call_from_thread(app._stop_glitch)
                            app.call_from_thread(app._show_shell_permission_prompt, command, reason, always_prompt)
                            _permission_event.wait()
                            state.permissions.awaiting_shell = False
                            app.call_from_thread(app._start_glitch)

                            if state.permissions.granted:
                                if state.permissions.shell_session_granted and not always_prompt:
                                    state.permissions.shell_session_allowed.add(command)

                                if command.strip().startswith("sudo "):
                                    state.ui.mode = "PASSWORD"
                                    app.call_from_thread(app._prompt_sudo_password)
                                    _permission_event.clear()
                                    _permission_event.wait()
                                    state.permissions.awaiting_shell = False
                                    _log_status, result_content = tool_shell_exec(tc_args)
                                else:
                                    _log_status, result_content = tool_shell_exec(tc_args)
                            else:
                                _log_status = "denied"
                                result_content = "Shell command denied by user."

                        line_count = len(result_content.split("\n"))
                        is_error = _log_status != "ok"
                        prefix = "▶ shell error" if is_error else "▶ shell output"
                        color = "red" if is_error else "dim cyan"
                        summary = f"  {prefix} ({line_count} lines)"
                        app.call_from_thread(app._write, "", Text(summary, style=color))
                    else:
                        # Destructive file operations: requires user confirmation (or session bypass)
                        diff_text = _build_diff(tc_args) if fname == "file_edit" else None
                        summary = _build_op_summary(fname, tc_args)
                        path_display = tc_args.get("path") or tc_args.get("old_path") or tc_args.get("filename") or tc_args.get("file", "?")

                        if fname in state.permissions.file_session_allowed:
                            _log_status, result_content = executor(tc_args)
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [{fname}] {path_display} → {result_content} (session)", style="green"),
                            )
                        else:
                            _permission_event.clear()
                            state.permissions.granted = False
                            app.call_from_thread(app._stop_glitch)
                            app.call_from_thread(app._show_tool_permission_prompt, fname, summary, diff_text)
                            _permission_event.wait()
                            state.permissions.awaiting = False
                            app.call_from_thread(app._start_glitch)

                            if state.permissions.granted:
                                if state.permissions.file_session_granted:
                                    state.permissions.file_session_allowed.add(fname)
                                    state.permissions.file_session_granted = False
                                _log_status, result_content = executor(tc_args)
                            else:
                                _log_status = "denied"
                                result_content = f"Operation '{fname}' denied by user."

                            color = "green" if _log_status == "ok" else ("yellow" if _log_status == "denied" else "red")
                            app.call_from_thread(
                                app._write, "",
                                Text(f"  [{fname}] {path_display} → {result_content}", style=color),
                            )

                    tool_result_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["tool_call_id"],
                        "content": result_content if isinstance(result_content, str) else str(result_content),
                    })

                api_msgs.extend(tool_result_msgs)

            raw_text = final_response or "I could not generate a compose response."
            state.session.messages.append({"role": "assistant", "content": raw_text})
            append_to_live_session("assistant", raw_text)

        except AuthenticationError:
            app.call_from_thread(
                app._write,
                "",
                Text(f"Authentication failed. Check your API key for '{state.provider.active}'.", style="bold red"),
            )
        except RateLimitError:
            app.call_from_thread(
                app._write,
                "",
                Text("Rate limit exceeded. Please wait before retrying.", style="bold red"),
            )
        except APIError as e:
            app.call_from_thread(app._write, "", Text(f"API error: {e}", style="bold red"))
        except Exception as e:
            app.call_from_thread(app._write, "", Text(f"Compose error: {e}", style="bold red"))
        finally:
            state.ui.is_thinking = False
            state.ui.cancel_requested = False
            app.call_from_thread(app._stop_glitch)
            app.call_from_thread(app._set_input_label, "You: ")
            app.call_from_thread(app._update_footer)
            app.call_from_thread(lambda: app.query_one("#user-input").focus())

    threading.Thread(target=_thread, daemon=True).start()
