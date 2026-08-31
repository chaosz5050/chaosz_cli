from chaosz.state import state
from chaosz.ui.app_compaction import compact_conversation


class _CompactionApp:
    def _write(self, *_args):
        pass

    def _update_footer(self):
        pass

    def call_from_thread(self, callback, *args):
        callback(*args)

    def _generate_summary(self, _messages):
        return "The project has a working main.py and needs a smoke test."

    def _estimate_tokens(self, messages):
        return sum(len(message.get("content", "")) for message in messages) // 4


def test_compaction_ends_with_user_continuation_for_ollama_templates():
    original_messages = state.session.messages
    state.session.messages = [
        {"role": "user", "content": "Build the todo app."},
        {"role": "assistant", "content": "I will start."},
    ]
    try:
        messages = compact_conversation(_CompactionApp())
    finally:
        state.session.messages = original_messages

    assert messages[-1]["role"] == "user"
    assert "[CONTEXT HANDOFF]" in messages[-1]["content"]
    assert "Continue the user's task" in messages[-1]["content"]
