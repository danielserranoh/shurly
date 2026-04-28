"""
FastMCP server bootstrapped from the existing FastAPI app.

Strategy (recorded in `mcp_server/README.md`): use `fastmcp` standalone with
`FastMCP.from_fastapi(...)` to auto-generate tools from the API's OpenAPI
schema.

Phase 5.2 layers two filters on top of the bare auto-generation:
  * `EXCLUDED_ROUTE_MAPS` — routes that are auto-generated but useless (or
    actively harmful) as MCP tools: the public redirect path, the tracking
    pixel, robots.txt, the bare landing, the readiness/liveness probes, and
    the legacy `/api/v1/stats/*` surface that was superseded by `/analytics/*`.
  * `MCP_TOOL_NAMES` — strips the verbose `_api_v1_<path>_<method>` suffix
    from FastAPI-generated operationIds so LLM-facing tool names read like
    `create_short_url` instead of `create_short_url_api_v1_urls_post`.

Phase 5.3 will add hand-curated tools alongside this auto-generated set.
Auth (Phase 5.4) and deployment (Phase 5.5) are still pending.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

from main import app as fastapi_app

# Routes that exist in the FastAPI app but should NOT be MCP tools.
#
# Public-facing infrastructure: an LLM driving the API has no business
# fetching the redirect path or the email pixel — those are end-user surfaces.
# Probes return health, not data the model can reason about. The legacy
# `/api/v1/stats/*` namespace was superseded by `/api/v1/analytics/*` and is
# kept only for backward compat with old clients.
EXCLUDED_ROUTE_MAPS: list[RouteMap] = [
    # Public unversioned routes (Phase 3.10.x) — the redirect path, tracking
    # pixel, base landing, and robots.txt are user-facing, not API surfaces.
    RouteMap(pattern=r"^/$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r"^/robots\.txt$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r"^/\{short_code\}$", mcp_type=MCPType.EXCLUDE),
    RouteMap(pattern=r"^/\{short_code\}/track$", mcp_type=MCPType.EXCLUDE),
    # Health probes — orchestrator-only, not LLM-facing.
    RouteMap(pattern=r"^/api/v1/health(/.*)?$", mcp_type=MCPType.EXCLUDE),
    # Legacy stats namespace — superseded by /api/v1/analytics/*.
    RouteMap(pattern=r"^/api/v1/stats(/.*)?$", mcp_type=MCPType.EXCLUDE),
]

# Maps FastAPI's auto-generated operationIds to clean MCP tool names.
#
# FastAPI generates operationIds as `<func_name>_<path_segments>_<method>`,
# which produces tool names like `create_short_url_api_v1_urls_post`. The
# leading `<func_name>` already conveys the intent, so we strip the rest.
#
# Keep this dict in sync with the FastAPI route handlers: when a route is
# added or its function renamed, add/update its entry here so the MCP tool
# name stays stable. Tests in `tests/test_mcp_tools.py` enforce coverage.
MCP_TOOL_NAMES: dict[str, str] = {
    # Auth
    "register_api_v1_auth_register_post": "register",
    "login_api_v1_auth_login_post": "login",
    "get_current_user_info_api_v1_auth_me_get": "get_current_user_info",
    "change_password_api_v1_auth_change_password_post": "change_password",
    "generate_api_key_api_v1_auth_api_key_generate_post": "generate_api_key",
    "revoke_api_key_api_v1_auth_api_key_delete": "revoke_api_key",
    # URLs
    "create_short_url_api_v1_urls_post": "create_short_url",
    "create_custom_url_api_v1_urls_custom_post": "create_custom_url",
    "list_urls_api_v1_urls_get": "list_urls",
    "delete_url_api_v1_urls__short_code__delete": "delete_url",
    "update_url_api_v1_urls__short_code__patch": "update_url",
    "update_url_tags_api_v1_urls__short_code__tags_patch": "update_url_tags",
    "bulk_tag_urls_api_v1_urls_bulk_tags_post": "bulk_tag_urls",
    "get_url_preview_api_v1_urls__short_code__preview_get": "get_url_preview",
    "refresh_url_preview_api_v1_urls__short_code__refresh_preview_post": "refresh_url_preview",
    # Redirect rules (Phase 3.10.2)
    "list_redirect_rules_api_v1_urls__short_code__rules_get": "list_redirect_rules",
    "create_redirect_rule_api_v1_urls__short_code__rules_post": "create_redirect_rule",
    "update_redirect_rule_api_v1_urls__short_code__rules__rule_id__patch": "update_redirect_rule",
    "delete_redirect_rule_api_v1_urls__short_code__rules__rule_id__delete": "delete_redirect_rule",
    # Campaigns
    "create_campaign_api_v1_campaigns_post": "create_campaign",
    "list_campaigns_api_v1_campaigns_get": "list_campaigns",
    "get_campaign_api_v1_campaigns__campaign_id__get": "get_campaign",
    "delete_campaign_api_v1_campaigns__campaign_id__delete": "delete_campaign",
    "export_campaign_api_v1_campaigns__campaign_id__export_get": "export_campaign",
    "update_campaign_tags_api_v1_campaigns__campaign_id__tags_patch": "update_campaign_tags",
    # Analytics
    "get_overview_stats_api_v1_analytics_overview_get": "get_overview_stats",
    "get_url_daily_stats_api_v1_analytics_urls__short_code__daily_get": "get_url_daily_stats",
    "get_url_weekly_stats_api_v1_analytics_urls__short_code__weekly_get": "get_url_weekly_stats",
    "get_url_geo_stats_api_v1_analytics_urls__short_code__geo_get": "get_url_geo_stats",
    "get_campaign_summary_api_v1_analytics_campaigns__campaign_id__summary_get": "get_campaign_summary",
    "get_campaign_users_api_v1_analytics_campaigns__campaign_id__users_get": "get_campaign_users",
    "get_orphan_visits_api_v1_analytics_orphan_visits_get": "get_orphan_visits",
    # Tags
    "list_tags_api_v1_tags_get": "list_tags",
    "create_tag_api_v1_tags_post": "create_tag",
    "update_tag_api_v1_tags__tag_id__patch": "update_tag",
    "delete_tag_api_v1_tags__tag_id__delete": "delete_tag",
}


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
    return FastMCP.from_fastapi(
        app=fastapi_app,
        name=name,
        route_maps=EXCLUDED_ROUTE_MAPS,
        mcp_names=MCP_TOOL_NAMES,
    )


# Module-level instance is what `python -m mcp_server` and any external
# embedders pick up. Kept lazily-evaluated against the current app object so
# changes to FastAPI routes during development hot-reload also take effect.
mcp_server: FastMCP = _build_mcp_server()
