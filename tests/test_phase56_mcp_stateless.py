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


def test_mcp_requires_the_trailing_slash(monkeypatch):
    """`/mcp` (no slash) is shadowed by the short-code redirect route.

    `redirect_router` is registered before the mount and owns `/{short_code}`,
    which matches the bare path `/mcp`. That route is GET-only, so a POST there
    returns 405 and never reaches the MCP app; a GET is treated as a lookup for
    the short code "mcp" and 404s.

    This is why `mcp_server/README.md` advertises `https://s.griddo.io/mcp/`
    with the slash. Pinned here so the documented URL and the routing cannot
    drift apart silently — if a future change makes the bare path work, this
    test should be updated deliberately, not discovered in production.
    """
    from starlette.testclient import TestClient

    with TestClient(_fresh_app(monkeypatch)) as client:
        with_slash = _rpc(client, "tools/list")
        without_slash = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers=MCP_HEADERS,
        )

    assert with_slash.status_code == 200, with_slash.text
    assert without_slash.status_code == 405, (
        "bare /mcp no longer 405s — routing changed; update the README and this test"
    )
