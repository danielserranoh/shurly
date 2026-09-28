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
    # Auth. No `register` since Phase 3.13.2: accounts come from signing in with Google.
    # No API key management, `login` or `change_password` since Phase 6.3.
    "get_current_user_info",
    # Organization (Phase 3.14.2): read-only, role changes stay out of the MCP
    "get_organization",
    "list_organization_members",
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
    # Phase 3.11 — single-URL detail + live OG preview for the dashboard redesign
    "get_url",
    "fetch_url_metadata",
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
    # Phase 5.3 — hand-curated tools
    "create_campaign_from_rows",
    "add_redirect_rule",
    "get_url_analytics_summary",
    "list_orphan_visits_grouped",
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
    legacy_prefixes = (
        "day_statistics",
        "week_statistics",
        "world_statistics",
        "main_statistics",
        "next_statistics",
    )
    leaked = {n for n in names if n.startswith(legacy_prefixes)}
    assert not leaked, f"Legacy stats routes leaked: {sorted(leaked)}"


def test_health_probes_excluded():
    """Health probes are orchestrator-only, not LLM-facing."""
    names = _list_tool_names()
    leaked = {n for n in names if n in {"liveness", "readiness"}}
    assert not leaked, f"Health probes leaked: {sorted(leaked)}"


def test_sign_in_and_passwords_stay_out_of_the_mcp():
    """Phase 3.13 — signing in with Google is a browser flow (redirects and a
    cookie), and only the signed-in person sets or removes a password: an assistant
    reading untrusted text could be talked into it. Sign-up with a password is off.
    """
    names = _list_tool_names()
    sign_in = ("register", "google_", "set_password", "remove_password")
    leaked = {n for n in names if n.startswith(sign_in)}
    assert not leaked, f"Sign-in or password tools exposed: {sorted(leaked)}"


def test_organization_changes_stay_out_of_the_mcp():
    """Phase 3.14.2 — role changes, removals, ownership handovers, adopting
    someone's links and the list of removed people it works from are web/API only.

    An assistant reading untrusted text (link titles, fetched pages) could be
    talked into "make X an owner".
    """
    names = _list_tool_names()
    governance = (
        "update_member_role",
        "remove_organization_member",
        "transfer_ownership",
        "adopt_personal_links",
        "list_removed_members",
    )
    leaked = {n for n in names if n.startswith(governance)}
    assert not leaked, f"Organization changes exposed as MCP tools: {sorted(leaked)}"


def test_api_key_management_stays_out_of_the_mcp():
    """Phase 6.3 — generating or revoking the API key is the person's to do, in
    Settings or through the API.

    An assistant reading untrusted text (a link title, a fetched page) could be
    talked into "generate a new API key": the new key would land in its context,
    which is why /auth/me no longer returns it, and the key the person uses would
    stop working.
    """
    names = _list_tool_names()
    leaked = {n for n in names if n.startswith(("generate_api_key", "revoke_api_key"))}
    assert not leaked, f"API key management exposed as MCP tools: {sorted(leaked)}"


def test_no_password_or_session_token_passes_through_the_mcp():
    """Phase 6.3 — `login` would put a JWT in the assistant's context, and both it
    and `change_password` take a password from it. The MCP is already signed in, so
    neither does anything there that the person needs.
    """
    names = _list_tool_names()
    leaked = {n for n in names if n.startswith(("login", "change_password"))}
    assert not leaked, f"Password tools exposed as MCP tools: {sorted(leaked)}"
