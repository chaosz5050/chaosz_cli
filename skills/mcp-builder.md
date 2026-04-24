---
name: python-mcp-builder
description: >
  Build a Python MCP (Model Context Protocol) server using FastMCP. Use this skill whenever
  the user wants to create, extend, or debug an MCP server in Python — even if they just say
  "build me an MCP for X", "add an MCP tool for Y", "make this API available as MCP", or
  "I want Chaosz CLI to talk to Z". Also trigger when the user asks about connecting a new
  service or API to their AI toolchain. Python/FastMCP only — not TypeScript.
---

# Python MCP Server Builder

You are building a Python MCP server using FastMCP. The goal is a clean, working server
the AI can actually use — not a demo, not a skeleton. Real tools, real error handling,
real output.

---

## Stack

- **Framework**: `mcp` (FastMCP) — `pip install mcp` or add to `pyproject.toml`
- **Validation**: Pydantic v2 (`BaseModel`, `Field`)
- **HTTP client**: `httpx` (async)
- **Transport**: `stdio` for local tools (default), `streamable_http` for remote
- **Python**: 3.11+, fully async

---

## Project Structure

```
your_service_mcp/
├── server.py          # Single file for simple servers (preferred)
└── pyproject.toml     # If using Poetry
```

For anything beyond ~5 tools, split:
```
your_service_mcp/
├── __init__.py
├── server.py          # FastMCP init + tool registration
├── client.py          # API client / auth
├── models.py          # Pydantic input models
└── tools/
    ├── reads.py       # Read-only tools
    └── writes.py      # Mutating tools
```

---

## Minimal Working Server

```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field, ConfigDict
import httpx
import json

mcp = FastMCP("myservice_mcp")

# --- Input Models ---

class SearchInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., description="Search query", min_length=1, max_length=200)
    limit: int = Field(default=10, description="Max results (1–50)", ge=1, le=50)

# --- Tools ---

@mcp.tool(
    name="myservice_search",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
async def myservice_search(params: SearchInput) -> str:
    """Search MyService for items matching the query.

    Args:
        params: SearchInput with query and optional limit.

    Returns:
        JSON string with list of results, each containing id, title, url.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.myservice.com/search",
                params={"q": params.query, "limit": params.limit},
                headers={"Authorization": f"Bearer {API_KEY}"},
            )
            response.raise_for_status()
            return json.dumps(response.json(), indent=2)
    except httpx.HTTPStatusError as e:
        return _http_error(e)
    except httpx.TimeoutException:
        return "Error: Request timed out. Try a simpler query or retry."
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"

# --- Entry Point ---

if __name__ == "__main__":
    mcp.run()  # stdio by default
```

---

## Pydantic v2 Patterns

Always use v2 style. v1 patterns will silently misbehave.

```python
from pydantic import BaseModel, Field, field_validator, ConfigDict

class CreateItemInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,   # Strip whitespace automatically
        validate_assignment=True,     # Validate on attribute assignment
        extra="forbid",              # Reject unknown fields
    )

    name: str = Field(..., min_length=1, max_length=100,
                      description="Item name (e.g., 'My Project')")
    priority: int = Field(default=1, ge=1, le=5,
                          description="Priority 1 (low) to 5 (high)")
    tags: list[str] = Field(default_factory=list,
                            description="Optional tags")

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v
```

---

## Error Handling

Centralize this — don't duplicate it in every tool:

```python
def _http_error(e: httpx.HTTPStatusError) -> str:
    status = e.response.status_code
    messages = {
        400: "Bad request. Check your parameters.",
        401: "Authentication failed. Check your API key.",
        403: "Permission denied. You may not have access to this resource.",
        404: "Not found. Check the ID or name is correct.",
        429: "Rate limited. Wait a moment before retrying.",
        500: "Server error on the remote API. Try again later.",
    }
    return f"Error {status}: {messages.get(status, e.response.text[:200])}"
```

Every tool should catch:
1. `httpx.HTTPStatusError` → use `_http_error()`
2. `httpx.TimeoutException` → user-friendly timeout message
3. `Exception` → `f"Error: {type(e).__name__}: {e}"` — never swallow silently

---

## Tool Annotations

Always set all four. They matter for how the AI decides to use the tool:

| Annotation | Meaning | When True |
|---|---|---|
| `readOnlyHint` | Doesn't change state | GET-style operations |
| `destructiveHint` | May delete/overwrite | DELETE, overwrite ops |
| `idempotentHint` | Safe to call twice | PUT-style ops |
| `openWorldHint` | Talks to external systems | Any API call |

---

## Naming Conventions

- Server name: `{service}_mcp` — e.g., `github_mcp`, `obsidian_mcp`
- Tool names: `{service}_{verb}_{noun}` — e.g., `github_create_issue`, `obsidian_search_notes`
- Input models: `{Verb}{Noun}Input` — e.g., `CreateIssueInput`, `SearchNotesInput`

Prefix tool names with the service so they don't collide when multiple MCPs are loaded.

---

## Local Storage with SQLite

For servers that store data locally (no external API), use `aiosqlite` with an
`@asynccontextmanager` helper. **The decorator is not optional** — without it,
`async with get_db() as db:` raises `AttributeError: 'async_generator' object
has no attribute '__aenter__'` at runtime (not caught by `py_compile`).

```python
import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

DATA_DIR = Path.home() / ".local" / "share" / "myservice_mcp"
DATABASE_PATH = DATA_DIR / "data.db"

@asynccontextmanager                          # ← required, not optional
async def get_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row        # lets you access columns by name
        await db.execute("PRAGMA foreign_keys = ON")   # SQLite FKs are off by default
        yield db

async def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    async with get_db() as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                created_at  TEXT NOT NULL
            )
            """
        )
        await db.commit()

# --- Entry Point ---
if __name__ == "__main__":
    import asyncio
    asyncio.run(_init_db())
    mcp.run()
```

Usage in tools:

```python
async with get_db() as db:
    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row is None:
        return json.dumps({"error": f"Item {item_id} not found."})
    return json.dumps(dict(row), indent=2)
```

Error helpers for DB tools (replace `_http_error`):

```python
def _db_error(e: aiosqlite.Error) -> str:
    return f"Database Error: {type(e).__name__}: {e}"
```

Catch pattern in every tool:

```python
try:
    async with get_db() as db:
        ...
except aiosqlite.Error as e:
    return _db_error(e)
except Exception as e:
    return f"Error: {type(e).__name__}: {e}"
```

---

## Authentication Patterns

### Environment variable (preferred)
```python
import os

API_KEY = os.environ.get("MYSERVICE_API_KEY", "")

if not API_KEY:
    raise RuntimeError(
        "MYSERVICE_API_KEY environment variable is not set. "
        "Export it before starting the server."
    )
```

### Shared async client with auth (for servers with many tools)
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def app_lifespan():
    client = httpx.AsyncClient(
        base_url="https://api.myservice.com",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=15.0,
    )
    yield {"client": client}
    await client.aclose()

mcp = FastMCP("myservice_mcp", lifespan=app_lifespan)

@mcp.tool()
async def myservice_get_item(item_id: str, ctx: Context) -> str:
    """Get a single item by ID."""
    client: httpx.AsyncClient = ctx.request_context.lifespan_state["client"]
    try:
        r = await client.get(f"/items/{item_id}")
        r.raise_for_status()
        return json.dumps(r.json(), indent=2)
    except httpx.HTTPStatusError as e:
        return _http_error(e)
```

---

## Pagination

For any tool that lists resources:

```python
class ListInput(BaseModel):
    limit: int = Field(default=20, ge=1, le=100,
                       description="Results per page")
    offset: int = Field(default=0, ge=0,
                        description="Skip this many results")

# In the tool response:
return json.dumps({
    "total": data["total"],
    "count": len(data["items"]),
    "offset": params.offset,
    "has_more": data["total"] > params.offset + len(data["items"]),
    "items": data["items"],
}, indent=2)
```

---

## Connecting to Chaosz CLI

Add to `~/.config/chaosz/config.json` under `mcp_servers`:

```json
{
  "mcp_servers": {
    "myservice": {
      "command": "python",
      "args": ["/path/to/your_service_mcp/server.py"],
      "env": {
        "MYSERVICE_API_KEY": "your-key-here"
      }
    }
  }
}
```

Or if using Poetry:
```json
{
  "command": "poetry",
  "args": ["run", "python", "server.py"],
  "cwd": "/path/to/your_service_mcp"
}
```

Verify connection with `/mcp list` in Chaosz CLI.

---

## Quick Checklist Before Shipping

- [ ] Server name follows `{service}_mcp` pattern
- [ ] All tool names prefixed with service name
- [ ] Every tool has a Pydantic input model with `Field` descriptions
- [ ] All four annotations set on every tool
- [ ] `_http_error()` helper used consistently
- [ ] API key loaded from env, not hardcoded
- [ ] All tools are `async def`
- [ ] Entry point: `if __name__ == "__main__": mcp.run()`
- [ ] Runtime tested — `py_compile` only checks syntax, not decorator or import errors. Run: `echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python server.py` and confirm you get a valid JSON response with a `tools` list

---

## Common Footguns

**Forgetting `async`**: Every tool must be `async def`. Sync tools block the event loop.

**Pydantic v1 style**: `class Config` inside models, `validator` decorator, `.dict()` — all deprecated. Use `model_config`, `field_validator`, `model_dump()`.

**Bare `except Exception: pass`**: Always log or return the error. Silent failures make the AI confused about why a tool "didn't work."

**Hardcoded credentials**: Even for personal tools. Env vars take 10 seconds and save future pain.

**No timeout on httpx**: Default is no timeout. Always set `timeout=10.0` or you'll hang indefinitely on a dead API.

**Testing before writing**: Never call `shell_exec` to compile or run a file before calling `file_write` to create it. Writing the file in your reasoning does not create it on disk — only `file_write` does. Always: write first, test after.

**Missing `@asynccontextmanager` on database helpers**: If you write `async def get_db()` with a `yield` inside, it becomes an async *generator* — not an async context manager. Using it with `async with get_db() as db:` raises `AttributeError: 'async_generator' object has no attribute '__aenter__'` at runtime. The fix is one line: add `@asynccontextmanager` from `contextlib`. `py_compile` won't catch this — you must do a runtime test.
