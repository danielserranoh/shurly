"""
Phase 8.4 — the MCP on the app's host only (tests/test_phase84_app_paths.py has the rest). On the
app's host, as before: `/mcp`'s 308 to `/mcp/`, the MCP itself, and its OAuth metadata at the root.
On a short domain none of them is there: `/mcp` is a link's code, the rest a 404.
"""

import pytest

pytest.importorskip("fastmcp")

from fastapi.testclient import TestClient  # noqa: E402

from server.core.config import settings  # noqa: E402
from tests import test_phase58_mcp_oauth as oauth  # noqa: E402

# The fixture, by assignment (imported by name, ruff reads its use as a redefinition): the MCP
# signing in with a fake Google, its public URL on oauth.ORIGIN, the app's host there.
google = oauth.google

APP, GO = "shurly.griddo.io", "go.griddo.io"
MCP_HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def app_host_set(monkeypatch):
    monkeypatch.setattr(settings, "mcp_public_url", f"https://{APP}/mcp")


class TestTheMcp:
    def test_on_the_app_host_its_308_and_itself(self, client, app_host_set):
        redirect = client.post("/mcp", headers={"Host": APP}, follow_redirects=False)
        mcp = client.post("/mcp/", json={}, headers={"Host": APP, **MCP_HEADERS})

        assert (redirect.status_code, redirect.headers["location"]) == (308, "/mcp/")
        assert mcp.status_code == 401  # the MCP's own answer to a call without a token

    def test_on_a_short_domain_none_of_it(self, client, app_host_set):
        """POST /mcp is a code's path, GET only, like any code's; under /mcp/, nothing."""
        posted = client.post("/mcp", headers={"Host": GO}, follow_redirects=False)
        under = client.post(
            "/mcp/", json={}, headers={"Host": GO, **MCP_HEADERS}, follow_redirects=False
        )

        assert posted.status_code == 405
        assert "www-authenticate" not in under.headers
        assert client.get("/mcp/authorize", headers={"Host": GO}).status_code == 404

    def test_without_an_app_host_on_every_host(self, client):
        redirect = client.post("/mcp", headers={"Host": GO}, follow_redirects=False)

        assert (redirect.status_code, redirect.headers["location"]) == (308, "/mcp/")


class TestItsOAuthMetadata:
    METADATA = (
        "/.well-known/oauth-protected-resource/mcp/",
        "/.well-known/oauth-authorization-server/mcp",
    )

    def test_on_the_app_host(self, google):
        with TestClient(oauth._task(google), base_url=oauth.ORIGIN) as client:
            for path in self.METADATA:
                assert client.get(path).status_code == 200, path

    def test_not_on_a_short_domain(self, google):
        with TestClient(oauth._task(google), base_url="https://go.shurly.test") as client:
            for path in self.METADATA:
                assert client.get(path).status_code == 404, path
