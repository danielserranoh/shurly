"""
MCP server for Shurly (Phase 5).

Exposes the existing FastAPI surface as an MCP server using FastMCP's
auto-generation from FastAPI. See `mcp_server/server.py` for the bootstrap
and `mcp_server/README.md` for the framework decision and local-dev workflow.
"""

from mcp_server.server import mcp_server

__all__ = ["mcp_server"]
