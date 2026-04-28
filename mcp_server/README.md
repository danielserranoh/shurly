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

Run the server as a subprocess and let an MCP client talk to it over stdin/stdout.

The repository ships a wrapper script that handles three things the MCP
client config can't easily express on a single line: changing into the
project root, opting into the `[mcp]` extra (`uv run --extra mcp`), and
setting `TESTING=1` so the FastAPI startup event doesn't try to reach
the private-VPC RDS from your laptop:

```bash
# Direct invocation (what the wrapper does internally)
./scripts/run_mcp_local.sh
```

Register with Claude Code (one-time, per dev machine):

```bash
claude mcp add shurly-local -- /Users/<you>/Tools/shurly/scripts/run_mcp_local.sh
```

Replace `<you>` with your username. The script resolves the project root
from its own path, so the registered command stays short and survives
moving the repo. After registration, any Claude Code session can list
the server via `/mcp` and invoke its tools.

If a previous registration was wrong (truncated by terminal wrap, missing
extras, etc.), remove it before re-adding:

```bash
claude mcp remove shurly-local
```

#### What `TESTING=1` does

`main.py`'s startup hook calls `Base.metadata.create_all()` and seeds the
default `Domain` row plus predefined tags. All three need a live DB
connection; the production RDS sits inside a private VPC, so a stdio
server running on your laptop can't reach it. The startup hook checks
`os.getenv("TESTING")` and short-circuits when set — same gate the test
suite uses. Tool **listing** doesn't need the DB and works fine. Tool
**invocation** against real data needs a live DB and is wired up in
Phase 5.4 (auth + per-user scoping against the deployed API).

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

## Auto-generated tool surface (Phase 5.2)

Phase 5.1 produced 47 raw tools — every FastAPI route, verbatim. Phase 5.2
filters and renames that set down to **36 LLM-facing tools** with clean names.

Two filters live in `mcp_server/server.py`:

- **`EXCLUDED_ROUTE_MAPS`** — drops public unversioned routes (`/`,
  `/{short_code}` redirect, `/{short_code}/track` pixel, `/robots.txt`),
  health probes (`/api/v1/health`, `/api/v1/health/db`), and the legacy
  `/api/v1/stats/*` namespace superseded by `/api/v1/analytics/*`.
- **`MCP_TOOL_NAMES`** — maps FastAPI's verbose auto-generated operationIds
  (`create_short_url_api_v1_urls_post`) to clean MCP tool names
  (`create_short_url`).

The 36-tool surface covers: auth (6), URL CRUD + tagging + previews (9),
redirect rules (4), campaigns (6), analytics (7), tags (4).

`tests/test_phase52_mcp_tools.py` pins this list. When a route is added or
renamed, the test fails until `MCP_TOOL_NAMES` (or `EXCLUDED_ROUTE_MAPS`) is
updated — forcing a deliberate decision rather than silent surface drift.

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
