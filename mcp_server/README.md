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

## Hand-curated tools (Phase 5.3)

Four workflows produce awkward shapes when projected straight from OpenAPI.
Phase 5.3 ships hand-written tools alongside the auto-generated set:

- **`create_campaign_from_rows`** — accepts `rows: list[dict]` instead of
  an embedded CSV string. Serialises in-memory and reuses the existing
  campaign generator (same uniqueness retry, same `user_data` shape).
- **`get_url_analytics_summary`** — composes totals + daily series + top
  countries into one call so the LLM doesn't chain `overview/daily/geo`.
- **`add_redirect_rule`** — sugar over `POST /urls/{code}/rules` with named
  condition args (`device="ios"`, `language="en"`, etc.) instead of a raw
  conditions list.
- **`list_orphan_visits_grouped`** — clusters orphan visits by
  `attempted_path` so typo patterns are obvious instead of paginating
  through a flat event log.

The pure logic lives in `mcp_server/curated.py` (takes `db: Session` and
`user: User` explicitly — easy to test). The MCP-facing wrappers in
`mcp_server/server.py` open a `SessionLocal` per call. **Auth resolution is
stubbed until Phase 5.4** — tool listing works; invocation raises a clear
`NotImplementedError` until the bearer-token plumbing lands.

Total tool surface after Phase 5.3: **40 tools** (36 auto-generated + 4
curated). The 5.2 contract test (`tests/test_phase52_mcp_tools.py`) and
the 5.3 logic tests (`tests/test_phase53_curated_tools.py`) together pin
the surface.

## Authentication (Phase 5.4)

The MCP server validates the inbound `Authorization: Bearer <token>`
against `User.api_key`. Both API keys and JWTs are accepted (token shape
disambiguates — JWTs have two dots, API keys never do). The same code path
backs the FastAPI `get_current_user` dependency, so a single key works in
either surface.

Two integration points:

1. **`ShurlyTokenVerifier`** (in `mcp_server/auth.py`) — fastmcp
   `TokenVerifier` subclass. Looks up the bearer in `User.api_key`,
   returns an `AccessToken` carrying the user id + email + scope.
   Returning `None` produces a 401 at the MCP layer.

2. **`forward_bearer`** — an httpx `Auth` hook attached via
   `httpx_client_kwargs={"auth": forward_bearer}`. The auto-generated
   tools call FastAPI through `httpx.AsyncClient(transport=ASGITransport)`.
   This hook re-attaches the inbound bearer to the outbound request so
   `get_current_user` resolves the same user.

Curated tools (Phase 5.3 wrappers) read the AccessToken via
`get_access_token()` and resolve the User row via
`resolve_current_user(db)` — no extra header plumbing needed.

### Generating an API key

```bash
# 1. Get a JWT via /auth/login (or use the existing dashboard).
# 2. Mint an API key:
curl -X POST https://s.griddo.io/api/v1/auth/api-key/generate \
  -H "Authorization: Bearer <jwt>"
# → {"api_key": "<32-byte url-safe>", "scope": "full_access"}
# 3. Use it in the MCP client config:
claude mcp add shurly --transport http \
    --url https://s.griddo.io/mcp \
    --header "Authorization: Bearer <api_key>"
```

Rotation: re-run `POST /auth/api-key/generate` to issue a new key (any
existing one is replaced). Revocation: `DELETE /auth/api-key`.

### Scope (`ApiKeyScope`)

The `User.api_key_scope` enum exists today (`FULL_ACCESS`, `READ_ONLY`,
`CREATE_ONLY`, `DOMAIN_SPECIFIC`) but only `FULL_ACCESS` is enforced.
Adding fine-grained enforcement is a future change — the column is
already on the AccessToken claims so MCP tools can branch on it once the
policy is decided.

### Local-dev escape hatch

`MCP_DISABLE_AUTH=1 ./scripts/run_mcp_local.sh` skips the verifier so
stdio sessions can list (and, once a DB is wired, invoke) tools without
a key. **Never set this in production.** The wrapper does not set it by
default.

## Roadmap reference

See `_pm/ROADMAP.md` § Phase 5 for the full sub-phase plan and the open
questions captured before bringup.
