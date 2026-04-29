"""
MCP server for Shurly (Phase 5).

Exposes the existing FastAPI surface as an MCP server using FastMCP's
auto-generation from FastAPI. See `mcp_server/server.py` for the bootstrap
and `mcp_server/README.md` for the framework decision and local-dev workflow.

Note: importing `mcp_server.server.mcp_server` triggers a lazy build of the
FastMCP instance via PEP 562 `__getattr__`. We deliberately avoid an eager
re-export here so importing the package during `main.create_app()` (Phase
5.5 mount) doesn't trigger the build before the FastAPI app is fully
constructed (the introspection target). Consumers must do
`from mcp_server.server import mcp_server` (stdio entry point) or call
`build_mcp_for_app(app)` (in-process mount).
"""
