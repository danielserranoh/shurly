"""
Phase 5.1 — FastMCP server bootstrapped from the existing FastAPI app.

Strategy (recorded in `mcp_server/README.md`): use `fastmcp` standalone with
`FastMCP.from_fastapi(...)` to auto-generate tools from the API's OpenAPI
schema. Phase 5.2 audits and refines the generated tool set; Phase 5.3 adds
hand-curated tools for workflows that don't translate cleanly (campaign CSV
import, composed analytics, etc.).

Auth is plumbed in Phase 5.4 — for now this is unauthenticated and intended
only for local dev (stdio transport against a local API).
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from main import app as fastapi_app


def _build_mcp_server() -> FastMCP:
    """
    Build the MCP server from the FastAPI app.

    Kept as a function so consumers (entry point, tests) can rebuild a fresh
    instance instead of sharing module-level state. The decorator order in
    FastAPI matters here: by the time we reach this function, `main.app` has
    all its routes registered, so the OpenAPI schema FastMCP introspects is
    complete.
    """
    name = os.getenv("MCP_SERVER_NAME", "shurly")
    return FastMCP.from_fastapi(app=fastapi_app, name=name)


# Module-level instance is what `python -m mcp_server` and any external
# embedders pick up. Kept lazily-evaluated against the current app object so
# changes to FastAPI routes during development hot-reload also take effect.
mcp_server: FastMCP = _build_mcp_server()
