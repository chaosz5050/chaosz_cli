"""
Provider-agnostic stream adapters for Chaosz CLI.

Each iterator wraps a raw provider stream and yields normalized StreamChunk
objects. Turn handlers iterate over these and never branch on provider type.

To add a new provider:
  1. Write _iter_<provider>(messages, tools, model) -> Iterator[StreamChunk].
  2. Add an elif branch in stream().
"""

import json
from dataclasses import dataclass, field
from typing import Iterator

from chaosz.state import state


@dataclass
class ToolCall:
    """A fully assembled tool call from the model."""
    id: str
    name: str
    arguments: str  # always a JSON string


@dataclass
class StreamChunk:
    """Normalized output from one provider stream event."""
    text: str = ""             # text fragment — append to full_response
    reasoning_line: str = ""   # one complete reasoning line — stream to UI immediately
    reasoning_block: str = ""  # post-hoc reasoning block — pass to _write_reasoning_block
    reasoning_content: str = ""  # full accumulated reasoning text — for provider follow-up echo-back
    tool_calls: list = field(default_factory=list)  # complete ToolCall list — final chunk only
    tool_delta: str = ""       # incremental tool argument delta
    tool_name: str = ""        # tool being streamed
    tool_id: str = ""          # tool call ID
    usage: dict | None = None  # {"prompt": int, "completion": int, "cached": int} — final chunk
    finish_reason: str | None = None  # "stop" | "tool_calls" | "length" | None


def _process_think_tags(
    content: str, buf: str, in_think: bool
) -> tuple[str, str, str, bool]:
    """
    Feed a content fragment through the <think>...</think> state machine.

    Handles partial tags at buffer boundaries by holding back the incomplete
    prefix. Returns (text_out, reasoning_out, new_buf, new_in_think).
    """
    buf += content
    text_out = ""
    reasoning_out = ""

    while True:
        if not in_think:
            if "<think>" in buf:
                idx = buf.index("<think>")
                text_out += buf[:idx]
                buf = buf[idx + len("<think>"):]
                in_think = True
            else:
                # Hold back any prefix that could be the start of <think>
                partial = buf.rfind("<")
                if partial != -1 and "<think>".startswith(buf[partial:]):
                    text_out += buf[:partial]
                    buf = buf[partial:]
                else:
                    text_out += buf
                    buf = ""
                break
        else:
            if "</think>" in buf:
                idx = buf.index("</think>")
                reasoning_out += buf[:idx]
                buf = buf[idx + len("</think>"):]
                in_think = False
            else:
                partial = buf.rfind("<")
                if partial != -1 and "</think>".startswith(buf[partial:]):
                    reasoning_out += buf[:partial]
                    buf = buf[partial:]
                else:
                    reasoning_out += buf
                    buf = ""
                break

    return text_out, reasoning_out, buf, in_think


def _split_reasoning_lines(text: str, buf: str) -> tuple[list[str], str]:
    """
    Split text on newlines, returning (complete_lines, remaining_partial_line).
    Prepends the existing buf so partial lines from previous calls are completed.
    """
    combined = buf + text
    parts = combined.split("\n")
    return parts[:-1], parts[-1]


def _flush_think_buf(think_buf: str, in_think: bool) -> Iterator[StreamChunk]:
    """Yield any remaining content in the think buffer after the stream ends."""
    if not think_buf:
        return
    if in_think:
        # Unclosed <think> — treat remainder as reasoning
        lines = think_buf.split("\n")
        for line in lines[:-1]:
            yield StreamChunk(reasoning_line=line)
        if lines[-1]:
            yield StreamChunk(reasoning_line=lines[-1])
    else:
        yield StreamChunk(text=think_buf)


def _ollama_think_value(model: str, reasoning_enabled: bool):
    """Return the best-effort Ollama think value for one model family."""
    if not reasoning_enabled:
        return None
    lower = model.lower()
    if "gpt-oss" in lower:
        return "medium"
    return True


def _ollama_needs_prompt_think_tag(model: str) -> bool:
    """Some Ollama models still respond better when nudged with a think tag."""
    return model.lower().startswith("gemma")


def _iter_gemini(messages: list, tools, model: str) -> Iterator[StreamChunk]:
    from chaosz.providers import get_gemini_client
    from google import genai

    client = get_gemini_client()

    # Separate system messages — Gemini takes them via system_instruction
    system_parts = [m["content"] for m in messages if m["role"] == "system" and m.get("content")]
    conversation = [m for m in messages if m["role"] != "system"]

    # Build tool_call_id → function name mapping for resolving tool results
    tool_call_id_to_name: dict[str, str] = {}
    for m in conversation:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            tool_call_id_to_name[tc["id"]] = fn.get("name", "unknown")

    # Convert Chaosz messages to Gemini Content objects
    contents = []
    for m in conversation:
        role = m["role"]
        if role == "assistant":
            parts = []
            if m.get("content"):
                parts.append(genai.types.Part(text=m["content"]))
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                parts.append(genai.types.Part(
                    function_call=genai.types.FunctionCall(name=fn["name"], args=args)
                ))
            if parts:
                contents.append(genai.types.Content(role="model", parts=parts))
        elif role == "tool":
            # Gemini expects function responses as "user" role.
            # Multiple consecutive tool results must be grouped into ONE Content —
            # Gemini enforces strict user/model alternation.
            fn_name = tool_call_id_to_name.get(m.get("tool_call_id", ""), "unknown")
            fn_part = genai.types.Part(
                function_response=genai.types.FunctionResponse(
                    name=fn_name,
                    response={"result": m.get("content") or ""},
                )
            )
            if (contents and contents[-1].role == "user"
                    and all(getattr(p, "function_response", None) for p in contents[-1].parts)):
                # Merge into the existing user Content for this batch of tool results
                contents[-1] = genai.types.Content(
                    role="user", parts=list(contents[-1].parts) + [fn_part]
                )
            else:
                contents.append(genai.types.Content(role="user", parts=[fn_part]))
        else:  # user
            content = m.get("content") or ""
            contents.append(genai.types.Content(role="user", parts=[genai.types.Part(text=content)]))

    # Convert Chaosz tools to Gemini Tools
    gemini_tools = None
    if tools:
        declarations = []
        for t in tools:
            fn = t["function"]
            declarations.append(genai.types.FunctionDeclaration(
                name=fn["name"],
                description=fn["description"],
                parameters=fn["parameters"]
            ))
        gemini_tools = [genai.types.Tool(function_declarations=declarations)]

    config = genai.types.GenerateContentConfig(
        tools=gemini_tools,
        system_instruction="\n\n".join(system_parts) if system_parts else None,
        automatic_function_calling=genai.types.AutomaticFunctionCallingConfig(disable=True)
    )

    raw_stream = client.models.generate_content_stream(
        model=model,
        contents=contents,
        config=config
    )

    accumulated_tool_calls = []
    prompt_tokens = 0
    completion_tokens = 0
    finish_reason_out: str | None = None

    for chunk in raw_stream:
        # Update token usage if available
        if chunk.usage_metadata:
            prompt_tokens = chunk.usage_metadata.prompt_token_count
            completion_tokens = chunk.usage_metadata.candidates_token_count

        if not chunk.candidates:
            continue

        candidate = chunk.candidates[0]
        if candidate.finish_reason:
            fr = str(candidate.finish_reason).split(".")[-1].lower()
            finish_reason_out = "length" if fr in ("max_tokens", "recitation") else fr
        if not candidate.content or not candidate.content.parts:
            continue

        for part in candidate.content.parts:
            if part.text:
                yield StreamChunk(text=part.text)
            if part.function_call:
                fc = part.function_call
                args_str = json.dumps(fc.args) if fc.args else "{}"
                # Gemini doesn't stream function call deltas, it sends them whole
                call_id = f"call_{len(accumulated_tool_calls)}"
                accumulated_tool_calls.append(ToolCall(
                    id=call_id,
                    name=fc.name,
                    arguments=args_str
                ))
                # Simulate streaming for the UI consistency
                for i in range(0, len(args_str), 32):
                    yield StreamChunk(
                        tool_delta=args_str[i:i+32],
                        tool_name=fc.name,
                        tool_id=call_id
                    )

    yield StreamChunk(
        tool_calls=accumulated_tool_calls,
        usage={"prompt": prompt_tokens, "completion": completion_tokens, "cached": 0},
        finish_reason=finish_reason_out,
    )


def _iter_ollama(messages: list, tools, model: str) -> Iterator[StreamChunk]:
    from chaosz.providers import get_native_ollama_client, prepare_messages_for_ollama

    think_value = _ollama_think_value(model, state.reasoning.enabled)

    # Gemma-family models are more reliable when prompted explicitly.
    if think_value and _ollama_needs_prompt_think_tag(model) and messages and messages[-1]["role"] == "user":
        if not messages[-1]["content"].strip().endswith("<|think|>"):
            messages = list(messages)
            messages[-1] = {**messages[-1], "content": messages[-1]["content"] + "\n<|think|>"}

    ollama_client = get_native_ollama_client()
    raw_stream = ollama_client.chat(
        model=model,
        messages=prepare_messages_for_ollama(messages),
        tools=tools,
        stream=True,
        think=think_value,
        options={"temperature": state.provider.temperature},
    )

    accumulated: dict[int, dict] = {}
    reasoning_buf = ""
    think_buf = ""
    in_think = False
    prompt_tokens = 0
    completion_tokens = 0
    finish_reason_out: str | None = None

    for chunk in raw_stream:
        msg = chunk.get("message", {})
        thinking = msg.get("thinking", "")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls") or []

        if thinking:
            lines, reasoning_buf = _split_reasoning_lines(thinking, reasoning_buf)
            for line in lines:
                yield StreamChunk(reasoning_line=line)

        if content:
            if not state.reasoning.enabled:
                yield StreamChunk(text=content)
            else:
                text_out, reason_out, think_buf, in_think = _process_think_tags(
                    content, think_buf, in_think
                )
                if text_out:
                    yield StreamChunk(text=text_out)
                if reason_out:
                    lines, reasoning_buf = _split_reasoning_lines(reason_out, reasoning_buf)
                    for line in lines:
                        yield StreamChunk(reasoning_line=line)

        # Ollama sends complete tool calls, not incremental deltas
        for idx, tc in enumerate(tool_calls):
            if idx not in accumulated:
                accumulated[idx] = {"id": "", "name": "", "arguments": ""}
            fn = tc.get("function", {})
            if tc.get("id"):
                accumulated[idx]["id"] = tc["id"]
            if fn.get("name"):
                accumulated[idx]["name"] = fn["name"]
            if fn.get("arguments"):
                args = fn["arguments"]
                accumulated[idx]["arguments"] = (
                    json.dumps(args) if isinstance(args, dict) else str(args)
                )

        if chunk.get("done_reason"):
            finish_reason_out = chunk["done_reason"]
        if chunk.get("prompt_eval_count"):
            prompt_tokens = chunk["prompt_eval_count"]
        if chunk.get("eval_count"):
            completion_tokens = chunk["eval_count"]

    # Flush remaining reasoning line buffer
    if reasoning_buf:
        yield StreamChunk(reasoning_line=reasoning_buf)

    # Flush remaining think tag buffer
    yield from _flush_think_buf(think_buf, in_think)

    tool_calls_out = []
    for _, e in sorted(accumulated.items()):
        tool_calls_out.append(ToolCall(id=e["id"], name=e["name"], arguments=e["arguments"]))
        # Simulate streaming for the UI
        args = e["arguments"]
        chunk_size = 32
        for i in range(0, len(args), chunk_size):
            yield StreamChunk(
                tool_delta=args[i:i+chunk_size],
                tool_name=e["name"],
                tool_id=e["id"]
            )

    yield StreamChunk(
        tool_calls=tool_calls_out,
        usage={"prompt": prompt_tokens, "completion": completion_tokens, "cached": 0},
        finish_reason=finish_reason_out,
    )


def _iter_mistral(messages: list, tools, model: str) -> Iterator[StreamChunk]:
    """Mistral adapter — delegates to OpenAI-compatible streaming."""
    return _iter_openai_compat(messages, tools, model)


def _iter_openai_compat(messages: list, tools, model: str) -> Iterator[StreamChunk]:
    from chaosz.providers import get_client, build_api_params

    client = get_client()
    raw_stream = client.chat.completions.create(
        **build_api_params(state.provider.active, model, messages, tools)
    )

    accumulated: dict[int, dict] = {}
    reasoning_buf = ""
    accumulated_reasoning = ""
    think_buf = ""
    in_think = False
    prompt_tokens = 0
    completion_tokens = 0
    cached_tokens = 0
    finish_reason_out: str | None = None

    for chunk in raw_stream:
        choice = chunk.choices[0] if chunk.choices else None
        if not choice:
            if chunk.usage:
                prompt_tokens = chunk.usage.prompt_tokens
                completion_tokens = chunk.usage.completion_tokens
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                if details:
                    cached_tokens = getattr(details, "cached_tokens", 0) or 0
            continue

        if choice.finish_reason:
            finish_reason_out = choice.finish_reason

        delta = choice.delta

        # Native reasoning field (DeepSeek-reasoner, Kimi, etc.)
        if state.reasoning.enabled:
            rc = getattr(delta, "reasoning_content", None) or getattr(delta, "thinking", None)
            if rc:
                accumulated_reasoning += rc
                lines, reasoning_buf = _split_reasoning_lines(rc, reasoning_buf)
                for line in lines:
                    yield StreamChunk(reasoning_line=line)

        if delta.content:
            if not state.reasoning.enabled:
                yield StreamChunk(text=delta.content)
            else:
                text_out, reason_out, think_buf, in_think = _process_think_tags(
                    delta.content, think_buf, in_think
                )
                if text_out:
                    yield StreamChunk(text=text_out)
                if reason_out:
                    lines, reasoning_buf = _split_reasoning_lines(reason_out, reasoning_buf)
                    for line in lines:
                        yield StreamChunk(reasoning_line=line)

        # OpenAI sends tool call deltas incrementally across chunks
        if delta.tool_calls:
            for tc in delta.tool_calls:
                idx = tc.index
                if idx not in accumulated:
                    accumulated[idx] = {"id": "", "name": "", "arguments": ""}
                if tc.id:
                    accumulated[idx]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        accumulated[idx]["name"] = tc.function.name
                    if tc.function.arguments:
                        args = tc.function.arguments
                        accumulated[idx]["arguments"] += args
                        yield StreamChunk(
                            tool_delta=args,
                            tool_name=accumulated[idx]["name"],
                            tool_id=accumulated[idx]["id"]
                        )

        if chunk.usage:
            prompt_tokens = chunk.usage.prompt_tokens
            completion_tokens = chunk.usage.completion_tokens
            # Standard OpenAI format
            details = getattr(chunk.usage, "prompt_tokens_details", None)
            if details:
                cached_tokens = getattr(details, "cached_tokens", 0) or 0
            # DeepSeek specific format
            ds_cached = getattr(chunk.usage, "prompt_cache_hit_tokens", 0)
            if ds_cached:
                cached_tokens = ds_cached

    # Flush remaining reasoning line buffer
    if reasoning_buf:
        yield StreamChunk(reasoning_line=reasoning_buf)

    # Flush remaining think tag buffer
    yield from _flush_think_buf(think_buf, in_think)

    tool_calls_out = [
        ToolCall(id=e["id"], name=e["name"], arguments=e["arguments"])
        for _, e in sorted(accumulated.items())
    ]
    yield StreamChunk(
        tool_calls=tool_calls_out,
        usage={"prompt": prompt_tokens, "completion": completion_tokens, "cached": cached_tokens},
        finish_reason=finish_reason_out,
        reasoning_content=accumulated_reasoning,
    )


def stream(messages: list, tools, model: str) -> Iterator[StreamChunk]:
    """
    Return the right stream iterator for the active provider.
    To add a new provider: write _iter_<provider>() and add an elif branch here.
    """
    if state.provider.active == "ollama":
        return _iter_ollama(messages, tools, model)
    if state.provider.active == "gemini":
        return _iter_gemini(messages, tools, model)
    if state.provider.active == "mistral":
        return _iter_mistral(messages, tools, model)
    return _iter_openai_compat(messages, tools, model)
