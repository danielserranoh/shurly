"""
Phase 5.2 — MCP tool surface contract.

Pins the exact list of tools the auto-generated MCP server exposes so that
adding a FastAPI route forces a deliberate decision: either add it to
`MCP_TOOL_NAMES` (with a clean tool name) or to `EXCLUDED_ROUTE_MAPS` (if it
shouldn't be an LLM-facing tool at all).

The `fastmcp` extra is optional, so tests skip when it's not installed.
"""

from __future__ import annotations

import asyncio

import pytest

fastmcp = pytest.importorskip("fastmcp")


EXPECTED_TOOLS: set[str] = {
    # Auth
    "register",
    "login",
    "get_current_user_info",
    "change_password",
    "generate_api_key",
    "revoke_api_key",
    # URLs
    "create_short_url",
    "create_custom_url",
    "list_urls",
    "delete_url",
    "update_url",
    "update_url_tags",
    "bulk_tag_urls",
    "get_url_preview",
    "refresh_url_preview",
    # Redirect rules
    "list_redirect_rules",
    "create_redirect_rule",
    "update_redirect_rule",
    "delete_redirect_rule",
    # Campaigns
    "create_campaign",
    "list_campaigns",
    "get_campaign",
    "delete_campaign",
    "export_campaign",
    "update_campaign_tags",
    # Analytics
    "get_overview_stats",
    "get_url_daily_stats",
    "get_url_weekly_stats",
    "get_url_geo_stats",
    "get_campaign_summary",
    "get_campaign_users",
    "get_orphan_visits",
    # Tags
    "list_tags",
    "create_tag",
    "update_tag",
    "delete_tag",
}


def _list_tool_names() -> set[str]:
    from mcp_server.server import _build_mcp_server

    server = _build_mcp_server()
    tools = asyncio.run(server.list_tools())
    return {t.name for t in tools}


def test_mcp_tool_surface_matches_expected():
    """Frozen tool surface — adding/removing a route must update this set."""
    actual = _list_tool_names()
    missing = EXPECTED_TOOLS - actual
    extra = actual - EXPECTED_TOOLS
    assert not missing, f"Tools missing from MCP server: {sorted(missing)}"
    assert not extra, (
        f"Unexpected tools exposed: {sorted(extra)}. "
        "Add them to EXPECTED_TOOLS, or filter via EXCLUDED_ROUTE_MAPS."
    )


def test_no_verbose_operationid_leaks():
    """No tool should still carry the FastAPI auto-generated path suffix."""
    names = _list_tool_names()
    leaks = {n for n in names if "_api_v1_" in n or "__" in n}
    assert not leaks, (
        f"Tools with un-renamed verbose names: {sorted(leaks)}. "
        "Add their operationId to MCP_TOOL_NAMES in mcp_server/server.py."
    )


def test_public_routes_are_excluded():
    """Public unversioned routes must never be MCP tools."""
    names = _list_tool_names()
    forbidden = {"redirect_short_url", "tracking_pixel", "robots_txt", "base_url_landing"}
    leaked = forbidden & names
    assert not leaked, f"Public routes leaked into MCP tools: {sorted(leaked)}"


def test_legacy_stats_excluded():
    """Legacy /api/v1/stats/* routes must never be MCP tools."""
    names = _list_tool_names()
    legacy_prefixes = ("day_statistics", "week_statistics", "world_statistics", "main_statistics", "next_statistics")
    leaked = {n for n in names if n.startswith(legacy_prefixes)}
    assert not leaked, f"Legacy stats routes leaked: {sorted(leaked)}"


def test_health_probes_excluded():
    """Health probes are orchestrator-only, not LLM-facing."""
    names = _list_tool_names()
    leaked = {n for n in names if n in {"liveness", "readiness"}}
    assert not leaked, f"Health probes leaked: {sorted(leaked)}"
