"""
Phase 5.5 — Streamable HTTP MCP transport mounted on the main FastAPI app.

These tests confirm the mount is wired up correctly. End-to-end MCP protocol
behavior is exercised by the existing 5.2 / 5.3 / 5.4 unit tests against the
FastMCP instance directly; here we just verify:

  * `/mcp` is mounted (i.e. fastmcp's StarletteWithLifespan is reachable via
    the FastAPI app's route table).
  * `MCP_DISABLE_MOUNT=1` opts out cleanly (escape hatch for incident response).
  * The mount doesn't shadow `/api/v1` routes or the public unversioned
    routes (`/`, `/{short_code}`, `/robots.txt`, `/{short_code}/track`).
"""

from __future__ import annotations

import importlib

import pytest

pytest.importorskip("fastmcp")


def _is_mcp_mount(route) -> bool:
    return type(route).__name__ == "Mount" and route.path == "/mcp"


def test_mcp_is_mounted_at_slash_mcp():
    import main as m

    importlib.reload(m)  # ensure a clean app instance for this test

    mounts = [r for r in m.app.routes if _is_mcp_mount(r)]
    assert len(mounts) == 1, "expected exactly one /mcp mount"
    inner = mounts[0].app
    # fastmcp returns a Starlette app subclass for the streamable-http transport.
    assert type(inner).__name__ == "StarletteWithLifespan"


def test_disable_mount_env_skips_mount(monkeypatch):
    monkeypatch.setenv("MCP_DISABLE_MOUNT", "1")
    import main as m

    importlib.reload(m)

    mounts = [r for r in m.app.routes if _is_mcp_mount(r)]
    assert mounts == [], "MCP_DISABLE_MOUNT=1 should suppress the mount"


def test_api_v1_routes_take_precedence_over_mcp_mount():
    """The mount sits at `/mcp`; nothing else should be shadowed."""
    import main as m

    importlib.reload(m)

    api_paths = [
        getattr(r, "path", None)
        for r in m.app.routes
        if type(r).__name__ == "APIRoute"
    ]
    # Must include at least the auth + redirect endpoints — sanity check that
    # the mount didn't accidentally swallow them.
    assert "/api/v1/auth/me" in api_paths
    assert "/{short_code}" in api_paths
    assert "/robots.txt" in api_paths


def test_app_state_carries_mcp_app_handle():
    """`main.create_app()` stores the mounted app on `app.state.mcp_app` so
    the lifespan can forward start/stop into the MCP session manager."""
    import main as m

    importlib.reload(m)
    assert getattr(m.app.state, "mcp_app", None) is not None
