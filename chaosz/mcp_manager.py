"""MCP (Model Context Protocol) server connection manager.

Bridges the async MCP Python SDK with Chaosz's synchronous/thread-based
architecture by running a dedicated asyncio event loop in a daemon thread.
All public functions are fully synchronous and safe to call from any thread.
"""

import asyncio
import os
import shlex
import threading
from dataclasses import dataclass, field

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

@dataclass
class McpServerConnection:
    name: str
    config: dict
    session: ClientSession | None = None
    tools: list[dict] = field(default_factory=list)  # OpenAI-format schemas
    prompts: list[str] = field(default_factory=list)  # resolved prompt text blocks
    error: str | None = None
    connected: bool = False
    _ctxs: tuple | None = None  # (transport_ctx, session_ctx) for cleanup


_connections: dict[str, McpServerConnection] = {}
_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Event loop management
# ---------------------------------------------------------------------------

def _get_loop() -> asyncio.AbstractEventLoop:
    """Return the shared daemon asyncio event loop, creating it on first call."""
    global _loop
    if _loop is not None:
        return _loop
    with _loop_lock:
        if _loop is not None:
            return _loop
        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        t = threading.Thread(target=_run, daemon=True, name="mcp-event-loop")
        t.start()
        _loop = loop
    return _loop


# ---------------------------------------------------------------------------
# Schema translation
# ---------------------------------------------------------------------------

def _mcp_tool_to_openai_schema(tool, server_name: str) -> dict:
    """Convert an MCP Tool object to an OpenAI function-calling schema dict.

    Prefixes the function name with 'mcp_{server_name}__' to avoid collisions
    with built-in tools and to allow fast dispatch via startswith("mcp_").
    """
    input_schema = tool.inputSchema or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": f"mcp_{server_name}__{tool.name}",
            "description": f"[MCP:{server_name}] {tool.description or tool.name}",
            "parameters": input_schema,
        },
    }


# ---------------------------------------------------------------------------
# Async connection helpers (run on the dedicated event loop)
# ---------------------------------------------------------------------------

async def _fetch_prompts_async(session: ClientSession, timeout: float = 10.0) -> list[str]:
    """Fetch and resolve all prompts from an MCP session. Returns list of text blocks."""
    try:
        prompts_resp = await asyncio.wait_for(session.list_prompts(), timeout=timeout)
        texts = []
        for p in prompts_resp.prompts:
            try:
                result = await asyncio.wait_for(
                    session.get_prompt(p.name, arguments={}), timeout=timeout
                )
                for msg in result.messages:
                    content = msg.content
                    if hasattr(content, "text"):
                        texts.append(content.text.strip())
            except Exception:
                pass
        return texts
    except Exception:
        return []


async def _connect_stdio_async(cfg: dict, timeout: float = 15.0):
    """Open a stdio MCP connection. Returns (session, mcp_tools, mcp_prompts, (transport_ctx, session_ctx))."""
    parts = shlex.split(cfg["command"])
    command, args = parts[0], parts[1:]
    server_params = StdioServerParameters(command=command, args=args, env=None)

    transport_ctx = stdio_client(server_params, errlog=open(os.devnull, "w"))
    read, write = await asyncio.wait_for(transport_ctx.__aenter__(), timeout=timeout)
    session_ctx = ClientSession(read, write)
    session = await asyncio.wait_for(session_ctx.__aenter__(), timeout=timeout)
    await asyncio.wait_for(session.initialize(), timeout=timeout)
    tools_resp = await asyncio.wait_for(session.list_tools(), timeout=timeout)
    prompts = await _fetch_prompts_async(session)
    return session, tools_resp.tools, prompts, (transport_ctx, session_ctx)


async def _connect_sse_async(cfg: dict, timeout: float = 15.0):
    """Open an SSE MCP connection. Returns (session, mcp_tools, mcp_prompts, (transport_ctx, session_ctx))."""
    url = cfg["url"]
    transport_ctx = sse_client(url)
    read, write = await asyncio.wait_for(transport_ctx.__aenter__(), timeout=timeout)
    session_ctx = ClientSession(read, write)
    session = await asyncio.wait_for(session_ctx.__aenter__(), timeout=timeout)
    await asyncio.wait_for(session.initialize(), timeout=timeout)
    tools_resp = await asyncio.wait_for(session.list_tools(), timeout=timeout)
    prompts = await _fetch_prompts_async(session)
    return session, tools_resp.tools, prompts, (transport_ctx, session_ctx)


async def _disconnect_conn_async(conn: McpServerConnection, timeout: float = 5.0) -> None:
    """Gracefully exit context managers for a connection."""
    if not conn._ctxs:
        return
    transport_ctx, session_ctx = conn._ctxs
    try:
        await asyncio.wait_for(session_ctx.__aexit__(None, None, None), timeout=timeout)
    except Exception:
        pass
    try:
        await asyncio.wait_for(transport_ctx.__aexit__(None, None, None), timeout=timeout)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public synchronous API
# ---------------------------------------------------------------------------

def connect_server(name: str, cfg: dict) -> McpServerConnection:
    """Connect to one MCP server. Blocks until done or timeout (~20 s).

    Safe to call from any thread. Stores the connection in _connections.
    Returns the McpServerConnection — check .connected and .error.
    """
    loop = _get_loop()
    conn = McpServerConnection(name=name, config=cfg)
    _connections[name] = conn

    async def _do() -> None:
        try:
            transport = cfg.get("transport", "stdio")
            if transport == "stdio":
                session, mcp_tools, mcp_prompts, ctxs = await _connect_stdio_async(cfg)
            else:
                session, mcp_tools, mcp_prompts, ctxs = await _connect_sse_async(cfg)
            conn.session = session
            conn._ctxs = ctxs
            conn.tools = [_mcp_tool_to_openai_schema(t, name) for t in mcp_tools]
            conn.prompts = mcp_prompts
            conn.connected = True
        except Exception as exc:
            conn.error = str(exc)
            conn.connected = False

    future = asyncio.run_coroutine_threadsafe(_do(), loop)
    try:
        future.result(timeout=20)
    except Exception as exc:
        conn.error = str(exc)
        conn.connected = False
    return conn


def disconnect_server(name: str) -> None:
    """Disconnect one server and remove it from the active connections dict."""
    conn = _connections.pop(name, None)
    if conn is None or not conn.connected:
        return
    loop = _get_loop()

    async def _do() -> None:
        await _disconnect_conn_async(conn)

    try:
        future = asyncio.run_coroutine_threadsafe(_do(), loop)
        future.result(timeout=8)
    except Exception:
        pass


def disconnect_all() -> None:
    """Gracefully disconnect all MCP servers. Call on app exit."""
    if not _connections:
        return
    loop = _get_loop()

    async def _do() -> None:
        for conn in list(_connections.values()):
            if conn.connected:
                await _disconnect_conn_async(conn)

    try:
        future = asyncio.run_coroutine_threadsafe(_do(), loop)
        future.result(timeout=10)
    except Exception:
        pass
    _connections.clear()


def call_tool(server_name: str, raw_tool_name: str, args: dict) -> tuple[str, str]:
    """Execute an MCP tool call synchronously.

    raw_tool_name is the original MCP tool name (without the mcp_ prefix).
    Returns (status, result_text) matching the pattern of all other tool executors.
    """
    conn = _connections.get(server_name)
    if not conn or not conn.connected or conn.session is None:
        return "error", f"MCP server '{server_name}' is not connected."

    loop = _get_loop()

    async def _do() -> str:
        result = await asyncio.wait_for(
            conn.session.call_tool(raw_tool_name, arguments=args),
            timeout=30.0,
        )
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif hasattr(block, "data"):
                parts.append(f"[binary data, {len(block.data)} bytes]")
        return "\n".join(parts) if parts else "(empty result)"

    try:
        future = asyncio.run_coroutine_threadsafe(_do(), loop)
        text = future.result(timeout=35)
        return "ok", text
    except Exception as exc:
        return "error", f"MCP tool call failed: {exc}"


def get_all_mcp_tools() -> list[dict]:
    """Return all OpenAI-format tool schemas from all connected MCP servers."""
    tools = []
    for conn in _connections.values():
        if conn.connected:
            tools.extend(conn.tools)
    return tools


def get_all_mcp_prompts() -> list[str]:
    """Return resolved prompt text blocks from all connected MCP servers."""
    prompts = []
    for conn in _connections.values():
        if conn.connected:
            prompts.extend(conn.prompts)
    return prompts


def get_connection_status() -> list[dict]:
    """Return status info for all active connections (for /mcp list display)."""
    return [
        {
            "name": conn.name,
            "connected": conn.connected,
            "tool_count": len(conn.tools),
            "error": conn.error,
            "enabled": conn.config.get("enabled", True),
            "transport": conn.config.get("transport", "?"),
        }
        for conn in _connections.values()
    ]
