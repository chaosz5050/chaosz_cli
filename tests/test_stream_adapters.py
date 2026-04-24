"""
Tests for the pure helper functions in stream_adapters.py.
No API calls, no state, no mocking required.
"""

from chaosz.stream_adapters import (
    StreamChunk,
    _flush_think_buf,
    _process_think_tags,
    _split_reasoning_lines,
)


# ---------------------------------------------------------------------------
# _process_think_tags
# ---------------------------------------------------------------------------

def test_process_think_tags_no_tags():
    """Plain text passes through unchanged."""
    text_out, reason_out, buf, in_think = _process_think_tags("hello world", "", False)
    assert text_out == "hello world"
    assert reason_out == ""
    assert buf == ""
    assert in_think is False


def test_process_think_tags_complete_tag():
    """A full <think>...</think> block is split correctly."""
    text_out, reason_out, buf, in_think = _process_think_tags(
        "before<think>reasoning here</think>after", "", False
    )
    assert text_out == "beforeafter"
    assert reason_out == "reasoning here"
    assert buf == ""
    assert in_think is False


def test_process_think_tags_split_across_chunks():
    """Opening tag arrives in one chunk, closing tag in the next.

    The function eagerly emits reasoning content when no partial tag boundary
    exists, so 'partial' comes out of the first chunk's reason_out (not buf).
    The combined reasoning across both chunks is 'partial reasoning'.
    """
    # First chunk: tag opens, 'partial' has no '<' so it's emitted immediately
    text_out1, reason_out1, buf1, in_think1 = _process_think_tags(
        "start<think>partial", "", False
    )
    assert text_out1 == "start"
    assert reason_out1 == "partial"
    assert in_think1 is True

    # Second chunk: tag closes
    text_out2, reason_out2, buf2, in_think2 = _process_think_tags(
        " reasoning</think>end", buf1, in_think1
    )
    assert reason_out2 == " reasoning"
    assert text_out2 == "end"
    assert in_think2 is False


def test_process_think_tags_unclosed_tag():
    """Unclosed <think> tag: content with no '<' is emitted eagerly via reason_out,
    in_think remains True so the caller knows the block is still open."""
    text_out, reason_out, buf, in_think = _process_think_tags(
        "text<think>unfinished", "", False
    )
    assert text_out == "text"
    assert reason_out == "unfinished"
    assert in_think is True


# ---------------------------------------------------------------------------
# _split_reasoning_lines
# ---------------------------------------------------------------------------

def test_split_reasoning_lines_complete_lines():
    """Newline-terminated input produces complete lines with no remainder."""
    lines, remainder = _split_reasoning_lines("line1\nline2\n", "")
    assert lines == ["line1", "line2"]
    assert remainder == ""


def test_split_reasoning_lines_partial_line():
    """Text without a trailing newline leaves a partial line in the buffer."""
    lines, remainder = _split_reasoning_lines("line1\npartial", "")
    assert lines == ["line1"]
    assert remainder == "partial"


def test_split_reasoning_lines_prepends_existing_buf():
    """Existing buffer is prepended so partial lines from prior chunks complete."""
    lines, remainder = _split_reasoning_lines(" rest\n", "start")
    assert lines == ["start rest"]
    assert remainder == ""


# ---------------------------------------------------------------------------
# _flush_think_buf
# ---------------------------------------------------------------------------

def test_flush_think_buf_empty():
    """Empty buffer yields nothing."""
    chunks = list(_flush_think_buf("", False))
    assert chunks == []


def test_flush_think_buf_outside_think():
    """Leftover text outside a think block is emitted as a text chunk."""
    chunks = list(_flush_think_buf("leftover text", False))
    assert len(chunks) == 1
    assert chunks[0].text == "leftover text"
    assert chunks[0].reasoning_line == ""


def test_flush_think_buf_inside_think():
    """Leftover text inside an unclosed think block is emitted as reasoning lines."""
    chunks = list(_flush_think_buf("line1\nline2", True))
    reasoning = [c.reasoning_line for c in chunks if c.reasoning_line]
    assert "line1" in reasoning
    assert "line2" in reasoning
