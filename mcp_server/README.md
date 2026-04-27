# Shurly MCP Server (Phase 5)

Exposes the Shurly API as a Model Context Protocol server, so MCP-aware
clients (Claude Code, Claude Desktop, custom agents) can drive Shurly via
natural-language tool calls.

This is Phase 5 of the project roadmap. Phase 5.1 (this commit) lands the
foundation: framework choice, package layout, local-dev entry point.
Subsequent sub-phases refine the tool set, plumb auth, and ship the deployed
HTTP surface.

## Framework choice

We use **`fastmcp` standalone** (the package by jlowin, on PyPI as `fastmcp`),
not `mcp.server.fastmcp` (the version of FastMCP that's bundled inside the
official Anthropic `mcp` SDK).

Three options were considered:

| Option | Why it could fit | Why we didn't pick it |
|---|---|---|
| `mcp` low-level SDK | Stable, Anthropic-blessed, follows the spec strictly | Verbose. Every tool is a hand-registered handler. No FastAPI integration. |
| `mcp.server.fastmcp` (official, bundled in the `mcp` SDK) | Decorator-based, ships with the official SDK, no extra dep | No `from_fastapi` shortcut. We'd hand-write every tool as a wrapper around the existing FastAPI route. |
| **`fastmcp` standalone** ✅ | `FastMCP.from_fastapi(app)` auto-generates the entire tool surface from the API's OpenAPI schema. Built-in auth helpers, mount support, OpenAPI export. | Third-party package; if Anthropic's bundled FastMCP diverges meaningfully, we'd need to migrate. Mitigation: bootstrap is a thin module, replaceable in <30 lines. |

The deciding factor was the auto-generation. Shurly's API already has rich
Pydantic schemas with descriptions, `responses` annotations, and explicit
status codes. `from_fastapi` projects all of that into MCP tool definitions
without us writing a single tool by hand. Phase 5.2 audits the result; for
the parts where the auto-generation produces awkward tool shapes (campaign
CSV import, composed analytics queries, redirect-rule sugar), Phase 5.3
adds hand-curated tools alongside.

If the standalone `fastmcp` ever stops being a good bet (upstream moves
incompatible, maintainer attention drops, Anthropic's official version
catches up), the migration is small: rewrite `server.py` with the new
framework, the rest of the application is untouched.

## Package layout

```
mcp_server/
├── __init__.py     # exposes mcp_server (the FastMCP instance)
├── __main__.py     # `python -m mcp_server` entry point — stdio or HTTP
├── server.py       # FastMCP.from_fastapi(...) bootstrap
└── README.md       # this file
```

The package is intentionally separate from `server/` so it can be packaged
and deployed independently if we want a separate Lambda/Fargate task for
the MCP surface (Phase 5.5 will decide). It depends on `main.app` (the
FastAPI application) for the routes, but doesn't otherwise touch the
HTTP server's runtime.

## Local development

Install the optional dependency:

```bash
uv sync --extra mcp --extra dev
```

### Stdio transport (Claude Code, Claude Desktop)

Run the server as a subprocess and let an MCP client talk to it over stdin/stdout:

```bash
uv run python -m mcp_server
```

In Claude Code, register it via the MCP config (one-time, per dev machine):

```bash
claude mcp add shurly-local -- uv run --directory /Users/<you>/Tools/shurly python -m mcp_server
```

Then in any Claude Code session, `/mcp` should list the `shurly-local`
server with the auto-generated tools.

### Streamable HTTP transport (deployed)

Useful for testing the transport that production will use (Phase 5.5).
Bind to a local port:

```bash
uv run python -m mcp_server --http --port 9000
```

The MCP endpoint is then reachable at `http://localhost:9000/mcp` (or
similar, depending on `fastmcp` defaults — check the startup log).

For programmatic clients:

```python
from fastmcp import Client

async with Client("http://localhost:9000/mcp") as client:
    tools = await client.list_tools()
    print([t.name for t in tools])
```

## What's auto-generated (Phase 5.1 baseline)

Every FastAPI route becomes an MCP tool, including:

- All `/api/v1/auth/*` endpoints (register, login, change-password, api-key)
- All `/api/v1/urls/*` endpoints (CRUD, OG preview, tagging)
- All `/api/v1/campaigns/*` endpoints (CSV upload included — see Phase 5.3 caveat)
- All `/api/v1/analytics/*` endpoints (overview, daily/weekly/geo, orphans)
- All `/api/v1/tags/*` endpoints
- All `/api/v1/urls/{code}/rules` endpoints (Phase 3.10.2 redirect rules)
- The public unversioned routes: `/{code}` redirect, `/{code}/track` pixel, `/robots.txt`, `/`

Phase 5.2 audits this list — some of these aren't useful as MCP tools
(the redirect path, the pixel, robots.txt are public-facing endpoints
that an LLM should never call directly). We'll filter them out of the
generated tool set.

Phase 5.3 adds hand-curated tools where auto-generation produces awkward
shapes. Likely candidates:

- `create_campaign_from_rows` — replaces multipart CSV upload with a
  JSON list of rows, easier to invoke from chat.
- `get_url_analytics_summary` — composes overview + daily + geo into one
  call so the LLM doesn't need three separate tool invocations.
- `add_redirect_rule` — sugar over `POST /urls/{code}/rules` with named
  args per condition type.
- `list_orphan_visits_grouped` — clusters by attempted_path so typos
  are obvious without paginating through a flat list.

## Authentication (Phase 5.4 — not yet)

Currently the MCP server inherits whatever the FastAPI app does (i.e.,
unauthenticated tools that hit the API would also be unauthenticated,
which is wrong for production). Phase 5.4 plumbs the existing
`User.api_key` + `ApiKeyScope` enum through the MCP `Authorization: Bearer`
header to scope tool calls per user.

Until then, this is **local-dev only**. Don't expose the HTTP transport
to the public internet without auth.

## Roadmap reference

See `_pm/ROADMAP.md` § Phase 5 for the full sub-phase plan and the open
questions captured before bringup.
