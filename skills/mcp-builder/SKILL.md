---
name: mcp-builder
description: Build, extend, debug, or verify Python FastMCP and Model Context Protocol servers, tools, and integrations. Use for MCP servers, MCP tools, or FastMCP.
---

# Python MCP Server Builder

Build a working MCP server, not a decorative skeleton or an untested collection of tool stubs.

## Build order

1. Inspect the target project and the API or data source. Confirm authentication, transport, and the minimum useful tools before creating files.
2. Start with a minimal stdio FastMCP server using Python 3.11+; keep it one file unless several tools genuinely need shared modules.
3. Give tools stable, service-prefixed names and precise docstrings. Define structured inputs with Pydantic v2 and reject invalid input early.
4. Use async I/O, explicit timeouts, and actionable errors. Read secrets from environment variables; never hardcode them or echo them in output.
5. Set tool annotations accurately: `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint`.
6. Update project metadata and give the user an exact launch/configuration command.
7. Verify tool discovery and one representative successful call before declaring completion. If live credentials are unavailable, verify the server starts and clearly label the remaining integration test.

## Constraints

- Prefer small, useful tools over thin wrappers around every endpoint.
- Keep output structured and bounded; return only data the model needs.
- Separate read-only tools from operations that change data, and make write consequences explicit.
- Do not claim the integration works solely because the code compiles.
