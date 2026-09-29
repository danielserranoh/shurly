"""
Personal data (docs/PERSONAL_DATA.md): every route and MCP tool has exactly one row, saying
what people's data it returns, who sees it, and the guard that decides. The guard must be in
the route's code, and the MCP column must match the tools. So a new route can't widen who sees
people's data without a row saying so, in the same PR.
"""

import ast
import asyncio
import inspect
import re
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("fastmcp")  # the MCP's routes and tools are part of the inventory

from fastapi.routing import APIRoute  # noqa: E402

DOC = Path(__file__).resolve().parent.parent / "docs" / "PERSONAL_DATA.md"
ROW = re.compile(
    r"^\| (?P<route>`[^`|]+`|MCP `[^`|]+`) \| (?P<data>[^|]+) \| (?P<who>[^|]+) \| "
    r"(?P<guard>[^|]+) \| (?P<mcp>[^|]+) \|$"
)
# The categories of people's data (docs/PERSONAL_DATA.md). The caller's own account isn't one.
PEOPLE = (
    "**recipients' rows**",
    "**recipients' activity**",
    "**visits**",
    "**addresses**",
    "**accounts**",
)
IGNORED_METHODS = {"HEAD", "OPTIONS"}  # answered for every route by the framework


def _rows() -> dict[str, re.Match]:
    rows: dict[str, re.Match] = {}
    for line in DOC.read_text().splitlines():
        row = ROW.match(line)
        if row is None:
            continue
        route = row["route"]
        key = f"MCP {route[5:-1]}" if route.startswith("MCP ") else route.strip("`")
        assert key not in rows, f"two rows for {key}"
        rows[key] = row
    return rows


def _guards(row: re.Match) -> list[str]:
    return re.findall(r"`([^`]+)`", row["guard"])


def _walk(routes, prefix=""):
    """(path, route) for every APIRoute, into routers FastAPI includes lazily (0.141)."""
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            yield from _walk(
                route.original_router.routes, prefix + (route.include_context.prefix or "")
            )
        elif isinstance(route, APIRoute):
            yield prefix + route.path, route


def _api_routes() -> dict[str, APIRoute]:
    from main import app

    return {
        f"{method} {path}": route
        for path, route in _walk(app.routes)
        for method in route.methods - IGNORED_METHODS
    }


def _mounted_routes(routes, prefix: str):
    for route in routes:
        path = prefix + getattr(route, "path", "")
        if type(route).__name__ == "Mount":
            yield from _mounted_routes(route.routes, path)
        else:
            yield path, route


@pytest.fixture
def mcp_routes(monkeypatch) -> dict:
    """The MCP's routes as production serves them: with Google sign-in (Phase 5.8)."""
    from pydantic import SecretStr

    from main import create_app
    from mcp_server.google_oauth import ShurlyGoogleProvider
    from mcp_server.server import build_mcp_auth
    from server.core.config import settings
    from server.utils.google_oidc import GoogleHttp
    from tests.conftest import TestingSessionLocal
    from tests.fake_google import CLIENT_ID, CLIENT_SECRET, FakeGoogle, FakeUpstream
    from tests.test_phase58_mcp_oauth import PUBLIC, SIGNING_KEY

    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", SecretStr(CLIENT_SECRET))
    monkeypatch.setattr(settings, "organization_domain", "griddo.io")
    monkeypatch.setattr(settings, "mcp_public_url", PUBLIC)
    monkeypatch.setattr(settings, "mcp_oauth_signing_key", SecretStr(SIGNING_KEY))
    google = FakeGoogle()

    class Provider(ShurlyGoogleProvider):
        def _create_upstream_oauth_client(self):
            return FakeUpstream(google)

    auth = build_mcp_auth(
        session_factory=TestingSessionLocal,
        provider_class=Provider,
        http_client=google.http2(),
        google_http=GoogleHttp(google.http()),
    )
    app = create_app(mcp_auth=auth)
    return {
        f"{method} {path}": route
        for path, route in _mounted_routes(app.state.mcp_app.routes, "/mcp")
        for method in (getattr(route, "methods", None) or set()) - IGNORED_METHODS
    }


def _tools() -> set[str]:
    from mcp_server.server import _build_mcp_server

    return {tool.name for tool in asyncio.run(_build_mcp_server().list_tools())}


def _generated_tool(key: str) -> str | None:
    """The MCP tool a route becomes, by its operationId (`MCP_TOOL_NAMES`), if any."""
    from main import app
    from mcp_server.server import MCP_TOOL_NAMES

    method, path = key.split(" ", 1)
    operation = app.openapi()["paths"].get(path, {}).get(method.lower())
    if operation is None:
        return None
    return MCP_TOOL_NAMES.get(operation["operationId"], operation["operationId"])


def _identifiers(function, depth: int = 2) -> set[str]:
    """Every name a function's code uses (its `Depends(…)` included), and those of the functions
    of its own module it calls, `depth` levels down."""
    module = inspect.getmodule(function)
    names: set[str] = set()
    visited: set = set()

    def visit(fn, level: int) -> None:
        if fn in visited:
            return
        visited.add(fn)
        own: set[str] = set()
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
            if isinstance(node, ast.Name):
                own.add(node.id)
            elif isinstance(node, ast.Attribute):
                own.add(node.attr)
        names.update(own)
        if level < depth:
            for name in own:
                helper = getattr(module, name, None)
                if inspect.isfunction(helper) and helper.__module__ == module.__name__:
                    visit(helper, level + 1)

    visit(function, 0)
    return names


def test_every_route_and_tool_has_one_row(mcp_routes):
    from mcp_server.server import MCP_TOOL_NAMES

    curated = {f"MCP {name}" for name in _tools() - set(MCP_TOOL_NAMES.values())}
    everything = set(_api_routes()) | set(mcp_routes) | curated
    rows = set(_rows())

    assert not everything - rows, f"no row in docs/PERSONAL_DATA.md: {sorted(everything - rows)}"
    assert not rows - everything, f"rows for nothing: {sorted(rows - everything)}"


def test_each_guard_is_in_its_code(mcp_routes):
    from mcp_server import curated

    rows = _rows()
    for key, route in _api_routes().items():
        guards, used = _guards(rows[key]), _identifiers(route.endpoint)
        if rows[key]["guard"].strip() == "public":
            assert not {"get_current_user", "get_signed_in_session"} & used, f"{key} isn't public"
        missing = [guard for guard in guards if guard not in used]
        assert not missing, f"{key}: its guard {missing} isn't in {route.endpoint.__name__}"
    for key, route in mcp_routes.items():
        if rows[key]["guard"].strip() != "public":
            assert _guards(rows[key]) == [route.name], key
    for key, row in rows.items():
        if key.startswith("MCP "):
            used = _identifiers(getattr(curated, key[4:])) | {"RequireAuthMiddleware"}
            missing = [guard for guard in _guards(row) if guard not in used]
            assert not missing, f"{key}: its guard {missing} isn't in curated.{key[4:]}"


def test_the_mcp_column_is_the_tools(mcp_routes):
    tools, rows = _tools(), _rows()
    for key in _api_routes():
        tool = _generated_tool(key)
        expected = f"`{tool}`" if tool in tools else "excluded"
        assert rows[key]["mcp"].strip() == expected, key
    for key in mcp_routes:
        assert rows[key]["mcp"].strip() == "n/a", key
    for key, row in rows.items():
        if key.startswith("MCP "):
            assert (row["mcp"].strip(), key[4:] in tools) == ("curated", True), key


def test_peoples_data_is_never_public_but_by_design():
    """Only a campaign link's redirect gives its recipient's data to anyone: personalization."""
    for key, row in _rows().items():
        if row["guard"].strip() == "public" and any(kind in row["data"] for kind in PEOPLE):
            assert "(by design)" in row["who"], f"{key} gives people's data to anyone"
