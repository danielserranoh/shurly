"""
Phase 8.4 — the paths the app serves itself, on its own host only. The user's choice (option A,
2026-10-02): the MCP, its OAuth metadata and the API's docs live on the app's host,
shurly.griddo.io (MCP_PUBLIC_URL's, else FRONTEND_URL's). On a short domain (go.griddo.io, and
s.griddo.io until the cutover), `/mcp`, `/docs` and `/redoc` are links like any other code:
Shlink's go.griddo.io/mcp points at a video, has 41 visits, and is out there.

Both hosts reach the same service (the ALB's rule 12), so the Host header decides. The ALB passes
the original one, and CloudFront forwards the viewer's for shurly.griddo.io (its origin request
policy, DEPLOYMENT.md § The distribution). X-Forwarded-Host is never read: anyone can send it.

- On a short domain, those paths resolve as `/{short_code}`: a redirect and a visit, or an orphan
  visit and a 404. Never Swagger, ReDoc or the OpenAPI document.
- A custom code is reserved only on the app host's domain: "mcp" on go.griddo.io is a link, and the
  import takes it (tests/test_phase84_shlink_import.py).
- With neither setting (local development, tests) there are no short domains: those paths are the
  app's on every host, and reserved on every domain, as before.

The MCP's side, which needs the [mcp] extra: tests/test_phase84_app_paths_mcp.py.
"""

import pytest

from server.app import urls as urls_module
from server.core.config import settings
from server.core.models import URL, Domain, OrphanVisit, URLType, Visitor
from server.utils.domain import app_host, get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata
from server.utils.url import RESERVED_SHORT_CODES, is_reserved_short_code

APP, GO = "shurly.griddo.io", "go.griddo.io"
# What each of the app's own pages has, and a link's redirect or 404 never does.
APP_PAGES = ("swagger-ui", "redoc.standalone", '"openapi":')


@pytest.fixture
def app_host_set(monkeypatch):
    """As production: the MCP and the frontend on shurly.griddo.io."""
    monkeypatch.setattr(settings, "mcp_public_url", f"https://{APP}/mcp")
    monkeypatch.setattr(settings, "frontend_url", f"https://{APP}")


@pytest.fixture
def go(db_session) -> Domain:
    domain = Domain(hostname=GO, is_default=False)
    db_session.add(domain)
    db_session.commit()
    return domain


@pytest.fixture
def no_og_fetch(monkeypatch):
    """Creating a link fetches its preview: never over the network in tests."""

    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


def _link(db, user, domain: Domain, code: str) -> URL:
    url = URL(
        short_code=code,
        original_url=f"https://example.com/{domain.hostname}/{code}",
        url_type=URLType.STANDARD,
        created_by=user.id,
        domain_id=domain.id,
    )
    db.add(url)
    db.commit()
    return url


def _get(client, path: str, host: str, **headers):
    return client.get(path, headers={"Host": host, **headers}, follow_redirects=False)


class TestTheAppHost:
    def test_mcp_public_urls_host_else_frontend_urls(self, monkeypatch):
        assert app_host() is None
        monkeypatch.setattr(settings, "frontend_url", "https://App.Shurly.Test/")
        assert app_host() == "app.shurly.test"
        monkeypatch.setattr(settings, "mcp_public_url", f"https://{APP}:443/mcp")
        assert app_host() == APP


class TestOnAShortDomain:
    def test_mcp_is_a_link_and_its_visit_is_logged(
        self, client, db_session, test_user, app_host_set, go
    ):
        link = _link(db_session, test_user, go, "mcp")

        response = _get(client, "/mcp", GO)

        assert (response.status_code, response.headers["location"]) == (302, link.original_url)
        assert (
            db_session.query(Visitor.short_code).filter(Visitor.url_id == link.id).scalar() == "mcp"
        )

    @pytest.mark.parametrize("code", sorted(RESERVED_SHORT_CODES))
    def test_every_path_the_app_keeps_for_itself_is_a_link(
        self, client, db_session, test_user, app_host_set, go, code
    ):
        """The other half of test_reserved_codes_cover_the_app_routes: what the app serves
        itself is reserved on its host, and a link on every other."""
        link = _link(db_session, test_user, go, code)

        response = _get(client, f"/{code}", GO)

        assert (response.status_code, response.headers["location"]) == (302, link.original_url)

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/mcp"])
    def test_without_a_link_an_orphan_visit_and_a_404(
        self, client, db_session, app_host_set, go, path
    ):
        response = _get(client, path, GO)

        assert response.status_code == 404
        assert not [page for page in APP_PAGES if page in response.text]
        assert db_session.query(OrphanVisit.attempted_path).scalar() == path

    def test_the_docs_oauth_redirect_isnt_there_either(self, client, app_host_set, go):
        response = _get(client, "/docs/oauth2-redirect", GO)

        assert response.status_code == 404

    def test_x_forwarded_host_is_never_read(self, client, db_session, test_user, app_host_set, go):
        link = _link(db_session, test_user, go, "docs")

        response = _get(client, "/docs", GO, **{"X-Forwarded-Host": APP})

        assert (response.status_code, response.headers["location"]) == (302, link.original_url)


class TestOnTheAppHost:
    @pytest.mark.parametrize(
        "host", [APP, "SHURLY.griddo.io", f"{APP}:443", f"{APP}."], ids=str.lower
    )
    def test_the_docs_and_the_openapi_document(self, client, app_host_set, host):
        """By the Host header, read as a redirect reads it: CloudFront forwards the viewer's."""
        assert "swagger-ui" in _get(client, "/docs", host).text
        assert "redoc.standalone" in _get(client, "/redoc", host).text
        assert _get(client, "/openapi.json", host).json()["openapi"]

    def test_its_links_still_resolve(self, client, db_session, test_user, app_host_set):
        """A code that isn't the app's own: on a host Shurly doesn't know as a domain, the
        default domain's link (3.10.1)."""
        link = _link(db_session, test_user, get_or_create_default_domain(db_session), "promo")

        response = _get(client, "/promo", APP)

        assert (response.status_code, response.headers["location"]) == (302, link.original_url)


class TestWithoutAnAppHost:
    def test_the_paths_are_the_apps_on_every_host(self, client, db_session, test_user, go):
        _link(db_session, test_user, go, "docs")

        assert "swagger-ui" in _get(client, "/docs", GO).text

    def test_reserved_on_every_domain(self):
        assert is_reserved_short_code("mcp", GO)
        assert is_reserved_short_code("docs", APP)


class TestReservation:
    def test_only_on_the_app_hosts_domain(self, app_host_set):
        assert is_reserved_short_code("mcp", APP)
        assert is_reserved_short_code("MCP", f"{APP}.")  # lowercased in loose mode, as a host is
        assert not is_reserved_short_code("mcp", GO)
        assert not is_reserved_short_code("promo", APP)

    def test_a_custom_mcp_on_a_short_domain(
        self, client, auth_headers, app_host_set, monkeypatch, no_og_fetch
    ):
        """After the cutover the default domain is go.griddo.io (8.3): a short domain."""
        monkeypatch.setattr(settings, "default_domain", GO)

        created = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com/video", "custom_code": "mcp"},
            headers=auth_headers,
        ).json()

        assert (created["short_code"], created["domain"], created.get("warning")) == (
            "mcp",
            GO,
            None,
        )
        response = _get(client, "/mcp", GO)
        assert (response.status_code, response.headers["location"]) == (
            302,
            "https://example.com/video",
        )

    def test_still_refused_on_the_app_hosts_domain(
        self, client, auth_headers, app_host_set, monkeypatch, no_og_fetch
    ):
        """Short links and the app on one host: there `/mcp` is the MCP."""
        monkeypatch.setattr(settings, "default_domain", APP)

        created = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com/video", "custom_code": "mcp"},
            headers=auth_headers,
        ).json()

        assert created["short_code"] != "mcp"
        assert "reserved" in created["warning"]
