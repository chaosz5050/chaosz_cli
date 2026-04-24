import re


def unescape_tool_delta(delta: str, buffer: str) -> tuple[str, str]:
    """
    Stateful unescaper for streaming JSON string fragments.

    The API streams raw JSON argument bytes incrementally, so a two-character
    escape sequence like \\n can be split across chunk boundaries (one chunk ends
    with '\\', the next starts with 'n'). We hold back any dangling trailing
    backslash in the buffer so it gets processed together with the next chunk.
    """
    full = buffer + delta

    # Hold back a dangling trailing backslash — it may be the start of \\n, \\", \\\\
    new_buffer = ""
    n_trailing = len(full) - len(full.rstrip("\\"))
    if n_trailing % 2 == 1:
        new_buffer = "\\"
        full = full[:-1]

    # Strip JSON structural prefixes (only relevant at the very start of a tool call stream)
    full = re.sub(r'^\{"path":"[^"]*","content":"', '', full)
    full = re.sub(r'^,"content":"', '', full)
    full = re.sub(r'^\{"edits":\[\{"search":"[^"]*","replace":"', '', full)
    full = re.sub(r'^,"replace":"', '', full)

    # Unescape JSON escape sequences.
    # Process \\\\ first so a literal backslash doesn't get re-escaped by later replacements.
    full = full.replace('\\\\', '\x00')  # \\ → placeholder
    full = full.replace('\\n', '\n')
    full = full.replace('\\t', '\t')
    full = full.replace('\\"', '"')
    full = full.replace('\x00', '\\')    # placeholder → \

    return full, new_buffer
