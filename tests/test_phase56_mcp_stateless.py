"""
Phase 5.6 — Stateless Streamable HTTP transport.

MCP revision `2026-07-28` removed protocol-level sessions: the
`initialize`/`notifications/initialized` handshake and the `Mcp-Session-Id`
header are gone, and every request carries its own protocol version and
capabilities in `_meta`.

`fastmcp` still defaults `stateless_http=False`, which keeps the pre-2026
behavior: the first call mints a session id and every later call must echo
it back. That breaks on our infra for two reasons, both of which these
tests pin down:

  * The ECS service scales to `maxTaskCount: 2` (scripts/deploy_ecs.sh) with
    no session affinity. A session minted on one task is unknown to the
    other, so once it scales out a share of requests fail with
    `-32600 Bad Request: Missing session ID`.
  * Every blue/green deploy replaces the tasks, dropping all live sessions.

These tests exercise the mounted app end to end rather than asserting on the
`stateless_http` kwarg, so they keep their meaning if fastmcp changes how the
flag is spelled or flips its default.
"""

from __future__ import annotations

import importlib
import json

import pytest

pytest.importorskip("fastmcp")

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _fresh_app(monkeypatch):
    """A freshly-built app with MCP auth off (these tests cover transport, not auth)."""
    monkeypatch.setenv("MCP_DISABLE_AUTH", "1")
    monkeypatch.delenv("MCP_DISABLE_MOUNT", raising=False)
    import main as m

    importlib.reload(m)
    return m.app


def _rpc(client, method: str, params: dict | None = None, request_id: int = 1):
    return client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {},
        },
        headers=MCP_HEADERS,
    )


def _payload(response):
    """Unwrap a JSON-RPC result from either a plain body or an SSE frame."""
    body = response.text
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    return json.loads(body)


def test_tools_list_needs_no_handshake(monkeypatch):
    """The core of the 2026-07-28 change: a bare `tools/list` must just work.

    Before this phase this returned `400 Missing session ID`, because fastmcp
    expected an `initialize` handshake first.
    """
    from starlette.testclient import TestClient

    with TestClient(_fresh_app(monkeypatch)) as client:
        response = _rpc(client, "tools/list")

    assert response.status_code == 200, response.text
    result = _payload(response)["result"]
    assert result["tools"], "expected a non-empty tool list"


def test_no_session_id_header_is_issued(monkeypatch):
    """`Mcp-Session-Id` was removed from the transport — we must not mint one."""
    from starlette.testclient import TestClient

    with TestClient(_fresh_app(monkeypatch)) as client:
        response = _rpc(client, "tools/list")

    assert response.headers.get("mcp-session-id") is None


def test_independent_requests_do_not_share_session_state(monkeypatch):
    """Two calls on separate connections must both succeed.

    This is the property that matters behind a load balancer: neither request
    may depend on state the other one established.
    """
    from starlette.testclient import TestClient

    app = _fresh_app(monkeypatch)

    with TestClient(app) as client:
        first = _rpc(client, "tools/list", request_id=1)
    with TestClient(app) as client:  # separate client == separate connection
        second = _rpc(client, "tools/list", request_id=2)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _payload(first)["result"]["tools"] == _payload(second)["result"]["tools"]


def test_curated_and_generated_tools_both_survive_stateless_mode(monkeypatch):
    """Going stateless must not drop either half of the tool surface.

    Phase 5.3 curated tools and the OpenAPI-generated ones are registered by
    different code paths, so assert one representative name from each.
    """
    from starlette.testclient import TestClient

    with TestClient(_fresh_app(monkeypatch)) as client:
        response = _rpc(client, "tools/list")

    names = {tool["name"] for tool in _payload(response)["result"]["tools"]}
    assert "get_url_analytics_summary" in names, "curated tool missing"
    assert "create_short_url" in names, "auto-generated tool missing"


def test_bare_mcp_path_redirects_to_the_mount(monkeypatch):
    """`/mcp` without the slash must get a client to the MCP app.

    It used to 405: `redirect_router` owns `/{short_code}`, which matches the
    bare path and is GET-only, so the mount never saw the request. Note the
    mount could not have answered anyway — a Starlette `Mount("/mcp")` compiles
    to `^/mcp(?P<path>/.*)$` and structurally does not match its own bare path,
    whatever the ordering. Hence an explicit 308 registered ahead of the
    redirect router.

    308 specifically: the redirect has to survive a POST carrying a JSON-RPC
    body, and 301/302 permit a client to drop it.
    """
    from starlette.testclient import TestClient

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(_fresh_app(monkeypatch)) as client:
        hop = client.post("/mcp", json=body, headers=MCP_HEADERS, follow_redirects=False)
        followed = client.post("/mcp", json=body, headers=MCP_HEADERS, follow_redirects=True)

    assert hop.status_code == 308, f"expected a body-preserving 308, got {hop.status_code}"
    assert hop.headers["location"] == "/mcp/"
    assert followed.status_code == 200, followed.text
    assert _payload(followed)["result"]["tools"]


def test_both_mcp_paths_return_the_same_tools(monkeypatch):
    """With and without the slash must be interchangeable, not merely both 200."""
    from starlette.testclient import TestClient

    with TestClient(_fresh_app(monkeypatch)) as client:
        bare = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers=MCP_HEADERS,
            follow_redirects=True,
        )
        slashed = _rpc(client, "tools/list")

    assert bare.status_code == slashed.status_code == 200
    assert _payload(bare)["result"]["tools"] == _payload(slashed)["result"]["tools"]


def _matching_route(app, path: str, method: str = "GET"):
    """The top-level route Starlette dispatches `method path` to, if any.

    Asserted at the routing layer on purpose: the alternative is issuing real
    requests, but the redirect and robots routes hit the database, and this app
    is built with the production `SessionLocal` — those calls would reach for
    RDS and time out.
    """
    from starlette.routing import Match

    scope = {
        "type": "http",
        "path": path,
        "root_path": "",
        "method": method,
        "headers": [],
        "query_string": b"",
    }
    best = None
    for route in app.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
        if match == Match.PARTIAL and best is None:
            best = route
    return best


def _is_mcp_mount(route) -> bool:
    return type(route).__name__ == "Mount" and route.path == "/mcp"


def test_only_the_literal_mcp_path_is_claimed(monkeypatch):
    """The regression guard: the reorder must cost exactly one short code.

    `/mcp` now belongs to the redirect route, but every other code —
    including ones that merely start with "mcp" — must still dispatch to the
    redirect resolver.
    """
    app = _fresh_app(monkeypatch)

    bare = _matching_route(app, "/mcp", "POST")
    assert bare is not None and getattr(bare, "path", None) == "/mcp", (
        "bare /mcp fell through to the short-code resolver again"
    )

    for code in ("abc123", "mcpx", "notmcp", "MCP"):
        route = _matching_route(app, f"/{code}")
        assert route is not None, f"/{code} matches nothing"
        assert not _is_mcp_mount(route), f"/{code} was swallowed by the mount"


def test_api_and_public_routes_survive_the_reorder(monkeypatch):
    """`/api/v1/*` and the public unversioned routes must be unaffected."""
    app = _fresh_app(monkeypatch)

    for path in ("/api/v1/auth/me", "/robots.txt", "/abc123"):
        route = _matching_route(app, path)
        assert route is not None, f"no route matches {path}"
        assert not _is_mcp_mount(route), f"{path} is shadowed by the /mcp mount"
