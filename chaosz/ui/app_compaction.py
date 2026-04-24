from rich.text import Text

from chaosz.config import build_system_prompt
from chaosz.providers import get_client, get_native_ollama_client
from chaosz.state import state


def estimate_tokens(_app, messages):
    """Approximate token count for a list of messages."""
    total_chars = sum(len(msg.get("content", "")) for msg in messages if msg.get("content"))
    return total_chars // 4


def filter_messages_for_summary(_app, messages):
    """Return only user/assistant text messages, excluding tool calls and tool results."""
    filtered = []
    for msg in messages:
        role = msg.get("role")
        if role == "tool":
            continue
        if role == "assistant" and "tool_calls" in msg:
            # Skip assistant messages that contain only tool calls
            if not msg.get("content"):
                continue
        filtered.append(msg)
    return filtered


def generate_summary(app, messages):
    """Generate a concise summary of filtered conversation using AI."""
    filtered = app._filter_messages_for_summary(messages)
    if not filtered:
        return "No conversation to summarize."

    # Build summary prompt
    summary_prompt = (
        "Please summarize the conversation concisely, focusing on key decisions, "
        "technical details, and user preferences. Keep the summary under 200 words."
    )
    summary_messages = [
        {"role": "system", "content": build_system_prompt()},
        *filtered,
        {"role": "user", "content": summary_prompt},
    ]

    try:
        if state.provider.active == "ollama":
            ollama_client = get_native_ollama_client()
            response = ollama_client.chat(
                model=state.provider.model,
                messages=summary_messages,
                stream=False,
            )
            return response.get("message", {}).get("content", "").strip()
        else:
            client = get_client()
            response = client.chat.completions.create(
                model=state.provider.model,
                messages=summary_messages,
                stream=False,
                timeout=45,
            )
            return response.choices[0].message.content.strip()
    except Exception as e:
        # Fallback: concatenate first 100 chars of each filtered message
        fallback = " | ".join(msg.get("content", "")[:100] for msg in filtered if msg.get("content"))
        return f"Summary generation failed: {e}. Fallback: {fallback[:500]}"



def compact_conversation(app, auto=False):
    """Compact the conversation, reset tokens, return new api_msgs list."""
    if state.background.compacting:
        return [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)

    state.background.compacting = True
    try:
        if auto:
            app.call_from_thread(app._write, "", Text("⚠ Context at 90% — auto-compacting...", style="yellow"))
        else:
            app.call_from_thread(app._write, "", Text("Compacting conversation...", style="cyan"))

        # Snapshot messages under the lock before the slow AI summarization call so we
        # don't hold the lock across a network request (Bug 1 fix: race condition).
        with state.session.lock:
            messages_snapshot = list(state.session.messages)
        summary = app._generate_summary(messages_snapshot)

        # Replace state.session.messages with compact representation under the lock
        with state.session.lock:
            state.session.messages = [
                {"role": "user", "content": f"[COMPACT] Previous conversation summary: {summary}"},
                {"role": "assistant", "content": "Understood. Continuing from the summary."},
            ]

        # Recompute estimate from the now-compact messages so the footer reflects reality
        new_api_msgs = [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)
        state.ui.ctx_estimated_tokens = app._estimate_tokens(new_api_msgs)

        # Update UI
        app.call_from_thread(app._write, "", Text("Context compacted. Session history summarized.", style="green"))
        app.call_from_thread(app._update_footer)

        # Return new api_msgs list for current loop
        return [{"role": "system", "content": build_system_prompt()}] + list(state.session.messages)
    finally:
        state.background.compacting = False


def check_and_compact_if_needed(app, api_msgs):
    """Check token usage and compact if >=90%. Returns updated api_msgs."""
    if state.background.compacting:
        return api_msgs

    estimated = app._estimate_tokens(api_msgs)
    state.ui.ctx_estimated_tokens = estimated  # keep footer in sync with actual api_msgs size
    ratio = estimated / state.provider.max_ctx if state.provider.max_ctx > 0 else 0
    if ratio >= 0.9:
        return app._compact_conversation(auto=True)
    return api_msgs
