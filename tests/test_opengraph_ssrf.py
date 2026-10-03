"""SSRF guard for the Open Graph fetcher (`server/utils/opengraph.py`).

Destination URLs are user-supplied, and the API server fetches them for link previews.
It must never reach loopback, private, link-local (cloud metadata) or other non-public
addresses: not by IP, not through a hostname, and not through a redirect.

Nothing here touches the network: for the duration of a test, the `dns` and `web`
fixtures replace `socket.getaddrinfo` with `FakeDNS` and route `httpx.AsyncClient`
through `FakeWeb` (an `httpx.MockTransport`).

The fetcher's log lines are covered here too: a failed fetch logs the destination
URL's origin, never its path or query string, which can carry personal data.
"""

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from server.core.config import Settings, settings
from server.utils.opengraph import OpenGraphMetadata, fetch_opengraph_metadata

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "151.101.1.69"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"

Route = Callable[[httpx.Request], httpx.Response]


class FakeDNS:
    """Stand-in for `socket.getaddrinfo`.

    IP literals resolve to themselves (as with the real resolver), names resolve via
    `records`, and anything else fails like NXDOMAIN, so no test can reach real DNS.
    """

    def __init__(self):
        self.records: dict[str, list[str]] = {}
        self.lookups: list[str] = []

    def getaddrinfo(self, host, port, *args, **kwargs):
        self.lookups.append(host)
        try:
            ipaddress.ip_address(host)
            addresses = [host]
        except ValueError:
            if host not in self.records:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
            addresses = self.records[host]
        port = port or 0
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, port, 0, 0))
            if ":" in address
            else (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))
            for address in addresses
        ]


class FakeWeb:
    """Stand-in for every HTTP server, behind `httpx.MockTransport`.

    Routes are keyed by Host header + path, because the request URL carries the pinned
    IP rather than the name. Unrouted requests get a 404.
    """

    def __init__(self):
        self.routes: dict[str, Route] = {}
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.headers["host"] + request.url.path)
        return route(request) if route else httpx.Response(404)


def page(title: str = "Public page") -> Route:
    """A page that declares its icon, so the fetcher asks for nothing else (Phase 8.7: without
    one, it tries the origin's /favicon.ico; tests/test_favicons.py)."""
    html = (
        f'<html><head><meta property="og:title" content="{title}">'
        '<link rel="icon" href="/icon.svg"></head></html>'
    )
    return lambda request: httpx.Response(200, html=html)


def redirect(location: str, status_code: int = 302) -> Route:
    return lambda request: httpx.Response(status_code, headers={"Location": location})


def fetch(url: str) -> OpenGraphMetadata:
    return asyncio.run(fetch_opengraph_metadata(url))


@pytest.fixture(autouse=True)
def guard_on(monkeypatch):
    """Pin the production default so a developer's local .env can't weaken these tests."""
    monkeypatch.setattr(settings, "og_fetch_allow_private", False)


@pytest.fixture
def dns(monkeypatch) -> FakeDNS:
    fake = FakeDNS()
    monkeypatch.setattr(socket, "getaddrinfo", fake.getaddrinfo)
    return fake


@pytest.fixture
def web(monkeypatch) -> FakeWeb:
    fake = FakeWeb()
    real_client = httpx.AsyncClient

    class MockedClient(real_client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(fake.handle), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", MockedClient)
    return fake


# Each address is served under a hostname: the guard has to check what a name resolves
# to, not what the URL says.
INTERNAL_ADDRESSES = [
    pytest.param("127.0.0.1", id="loopback"),
    pytest.param("::1", id="loopback-v6"),
    pytest.param("10.1.2.3", id="rfc1918-10"),
    pytest.param("172.16.0.1", id="rfc1918-172"),
    pytest.param("192.168.1.1", id="rfc1918-192"),
    pytest.param("169.254.169.254", id="ec2-instance-metadata"),
    pytest.param("169.254.170.2", id="ecs-task-metadata"),
    pytest.param("fe80::1", id="link-local-v6"),
    pytest.param("fd00::1", id="unique-local-v6"),
    pytest.param("100.64.0.1", id="shared-cgnat"),  # not is_private; only is_global catches it
    pytest.param("0.0.0.0", id="unspecified"),
    pytest.param("::", id="unspecified-v6"),
    pytest.param("224.0.0.1", id="multicast"),  # is_global is True for multicast
    pytest.param("ff02::1", id="multicast-v6"),
    pytest.param("240.0.0.1", id="reserved"),
    pytest.param("::ffff:169.254.169.254", id="ipv4-mapped"),
    pytest.param("64:ff9b::a9fe:a9fe", id="nat64"),
    pytest.param("2002:a9fe:a9fe::1", id="6to4"),  # older Pythons count 2002::/16 as global
]


@pytest.mark.parametrize("address", INTERNAL_ADDRESSES)
def test_host_resolving_to_internal_address_is_not_fetched(dns, web, address):
    dns.records["attacker.test"] = [address]
    web.routes["attacker.test/"] = page("Internal admin")

    assert not fetch("http://attacker.test/").has_metadata()
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://[::1]:8080/",
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://10.0.0.5/",
        "https://192.168.1.1/",
        "http://[fd00::1]/",
    ],
)
def test_internal_url_is_not_fetched(dns, web, url):
    dns.records["localhost"] = ["::1", "127.0.0.1"]

    assert not fetch(url).has_metadata()
    assert web.requests == []


def test_host_is_refused_if_any_address_is_internal(dns, web):
    """An attacker controls their own zone: one public record doesn't vouch for the rest."""
    dns.records["mixed.test"] = [PUBLIC_IP, "10.0.0.5"]
    web.routes["mixed.test/"] = page()

    assert not fetch("https://mixed.test/").has_metadata()
    assert web.requests == []


def test_unresolvable_host_returns_empty_metadata(dns, web):
    assert not fetch("https://no-such-host.test/").has_metadata()
    assert web.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "gopher://example.com/_",
        "dict://example.com:11211/",
        "javascript:alert(1)",
    ],
)
def test_non_http_scheme_is_refused_before_any_lookup(dns, web, url):
    dns.records["example.com"] = [PUBLIC_IP]

    assert not fetch(url).has_metadata()
    assert dns.lookups == []
    assert web.requests == []


def test_public_url_is_fetched(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    web.routes["example.com/article"] = page("Public page")

    metadata = fetch("https://example.com/article")

    assert metadata.title == "Public page"
    assert metadata.url == "https://example.com/article"


def test_user_agent_names_a_host_that_exists(dns, web):
    """A site owner who finds the fetcher in their logs follows its URL to see who it is."""
    dns.records["example.com"] = [PUBLIC_IP]
    web.routes["example.com/article"] = page()

    fetch("https://example.com/article")

    [request] = web.requests
    assert (
        request.headers["user-agent"] == "Shurly/1.0 (+https://shurly.griddo.io; Link Preview Bot)"
    )


def test_request_is_pinned_to_the_checked_address(dns, web):
    """httpx must not resolve the name a second time: a DNS-rebinding attacker would answer
    that lookup with an internal IP. The connection goes to the address that was checked,
    while the Host header and TLS (SNI + certificate check) keep the real hostname."""
    dns.records["example.com"] = [PUBLIC_IP]
    web.routes["example.com:8443/page"] = page()

    assert fetch("https://example.com:8443/page?ref=1").has_metadata()

    [request] = web.requests
    assert request.url == httpx.URL(f"https://{PUBLIC_IP}:8443/page?ref=1")
    assert request.headers["host"] == "example.com:8443"
    assert request.extensions["sni_hostname"] == "example.com"
    assert dns.lookups == ["example.com"]


def test_falls_back_to_next_address_when_one_is_unreachable(dns, web):
    """Pinning bypasses httpx's own multi-address connect, so the guard has to fall back
    itself, e.g. for an AAAA record on a host without IPv6 connectivity."""
    dns.records["example.com"] = [PUBLIC_IPV6, PUBLIC_IP]

    def unreachable_over_ipv6(request: httpx.Request) -> httpx.Response:
        if request.url.host == PUBLIC_IPV6:
            raise httpx.ConnectError("Network is unreachable", request=request)
        return page("Reached over IPv4")(request)

    web.routes["example.com/"] = unreachable_over_ipv6

    assert fetch("https://example.com/").title == "Reached over IPv4"
    assert [r.url.host for r in web.requests] == [PUBLIC_IPV6, PUBLIC_IP]


def test_redirect_to_internal_address_is_not_followed(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    web.routes["example.com/go"] = redirect("http://169.254.169.254/latest/meta-data/")
    web.routes["169.254.169.254/latest/meta-data/"] = page("ami-id")

    assert not fetch("https://example.com/go").has_metadata()
    assert [r.headers["host"] for r in web.requests] == ["example.com"]


def test_redirect_to_name_resolving_internally_is_not_followed(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    dns.records["intranet.corp"] = ["10.0.0.5"]
    web.routes["example.com/go"] = redirect("https://intranet.corp/wiki")
    web.routes["intranet.corp/wiki"] = page("Internal wiki")

    assert not fetch("https://example.com/go").has_metadata()
    assert [r.headers["host"] for r in web.requests] == ["example.com"]


def test_redirect_to_non_http_scheme_is_not_followed(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    web.routes["example.com/go"] = redirect("file:///etc/passwd")

    assert not fetch("https://example.com/go").has_metadata()
    assert len(web.requests) == 1


def test_public_redirects_are_followed(dns, web):
    """Relative Locations resolve against the hostname, never against the pinned IP."""
    dns.records["example.com"] = [PUBLIC_IP]
    dns.records["www.example.org"] = [OTHER_PUBLIC_IP]
    web.routes["example.com/old"] = redirect("/new", 301)
    web.routes["example.com/new"] = redirect("https://www.example.org/final", 308)
    web.routes["www.example.org/final"] = page("Final page")

    assert fetch("http://example.com/old").title == "Final page"
    assert [(r.headers["host"], r.url.host) for r in web.requests] == [
        ("example.com", PUBLIC_IP),
        ("example.com", PUBLIC_IP),
        ("www.example.org", OTHER_PUBLIC_IP),
    ]


def _redirect_chain(web: FakeWeb, hops: int) -> None:
    """/0 → /1 → … → /<hops>, where the last path serves the page."""
    for i in range(hops):
        web.routes[f"example.com/{i}"] = redirect(f"/{i + 1}")
    web.routes[f"example.com/{hops}"] = page("End of chain")


def test_follows_up_to_five_redirects(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    _redirect_chain(web, hops=5)

    assert fetch("https://example.com/0").title == "End of chain"


def test_gives_up_after_five_redirects(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    _redirect_chain(web, hops=6)

    assert not fetch("https://example.com/0").has_metadata()
    assert len(web.requests) == 6  # the original request + 5 followed redirects


def test_allow_private_setting_lets_local_development_preview_localhost(dns, web, monkeypatch):
    monkeypatch.setattr(settings, "og_fetch_allow_private", True)
    dns.records["localhost"] = ["127.0.0.1"]
    web.routes["localhost:4232/landing"] = page("Local draft")

    assert fetch("http://localhost:4232/landing").title == "Local draft"
    [request] = web.requests
    assert request.url.host == "127.0.0.1"  # still pinned: only the address check is relaxed


def test_allow_private_setting_is_off_by_default():
    assert Settings.model_fields["og_fetch_allow_private"].default is False


@pytest.mark.integration
@pytest.mark.real_og_fetch
class TestPreviewEndpointsUseTheGuard:
    """Every endpoint that fetches previews is covered, and a refused fetch never fails
    the request: it just yields no preview metadata."""

    def test_create_url(self, client: TestClient, auth_headers: dict, dns, web):
        r = client.post(
            "/api/v1/urls",
            json={"url": "http://169.254.169.254/latest/meta-data/"},
            headers=auth_headers,
        )

        assert r.status_code == 201
        assert r.json()["og_title"] is None
        assert dns.lookups == ["169.254.169.254"]
        assert web.requests == []

    def test_create_custom_url(self, client: TestClient, auth_headers: dict, dns, web):
        dns.records["localhost"] = ["::1", "127.0.0.1"]

        r = client.post(
            "/api/v1/urls/custom",
            json={"url": "http://localhost:8000/admin", "custom_code": "ssrf-probe"},
            headers=auth_headers,
        )

        assert r.status_code == 201
        assert r.json()["og_title"] is None
        assert dns.lookups == ["localhost"]
        assert web.requests == []

    def test_refresh_preview(self, client: TestClient, auth_headers: dict, dns, web):
        dns.records["intranet.corp"] = ["10.0.0.5"]
        created = client.post(
            "/api/v1/urls", json={"url": "https://intranet.corp/"}, headers=auth_headers
        )
        assert created.status_code == 201

        r = client.post(
            f"/api/v1/urls/{created.json()['short_code']}/refresh-preview",
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json()["og_title"] is None
        assert dns.lookups == ["intranet.corp", "intranet.corp"]  # create, then refresh
        assert web.requests == []

    def test_fetch_metadata(self, client: TestClient, auth_headers: dict, dns, web):
        """The live-preview endpoint returns whatever it fetched straight to the caller,
        which makes it the most direct way to read an internal page."""
        dns.records["preview.attacker.test"] = ["169.254.169.254"]
        web.routes["preview.attacker.test/latest/meta-data/"] = page("ami-id")

        r = client.post(
            "/api/v1/urls/fetch-metadata",
            json={"url": "http://preview.attacker.test/latest/meta-data/"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json() == {"og_title": None, "og_description": None, "og_image_url": None}
        assert dns.lookups == ["preview.attacker.test"]
        assert web.requests == []


# ---------------------------------------------------------------------------
# Log lines
# ---------------------------------------------------------------------------

# The root logger has no handler, so Python's last-resort handler prints these
# warnings to stderr, and in production that's CloudWatch.
EMAIL = "jane.doe@acme.example"
PERSONAL_URL = f"https://acme.test/in/jane-doe?email={EMAIL}"


def fails_with(error: Exception) -> Route:
    def route(request: httpx.Request) -> httpx.Response:
        raise error

    return route


@pytest.fixture
def og_log(caplog):
    caplog.set_level(logging.INFO, logger="server.utils.opengraph")
    return caplog


def assert_logged_without_path_or_query(log, line: str):
    assert line in log.messages  # the failure is still logged, with the URL's origin
    assert "jane-doe" not in log.text
    assert EMAIL not in log.text


class TestLogLines:
    """A failed fetch logs the URL's origin (scheme, host, port), never its path or query."""

    def test_http_error(self, dns, web, og_log):
        dns.records["acme.test"] = [PUBLIC_IP]  # no route: FakeWeb answers 404

        fetch(PERSONAL_URL)

        assert_logged_without_path_or_query(og_log, "Failed to fetch https://acme.test: HTTP 404")

    def test_refused_address(self, dns, web, og_log):
        dns.records["acme.test"] = ["10.0.0.5"]

        fetch(PERSONAL_URL)

        assert_logged_without_path_or_query(
            og_log,
            "Refused to fetch metadata from https://acme.test: "
            "acme.test resolves to non-public 10.0.0.5",
        )

    def test_refused_redirect(self, dns, web, og_log):
        """The refusal's own message named the whole URL of the hop."""
        dns.records["acme.test"] = [PUBLIC_IP]
        web.routes["acme.test/in/jane-doe"] = redirect(f"ftp://files.test/{EMAIL}")

        fetch(PERSONAL_URL)

        assert_logged_without_path_or_query(
            og_log,
            "Refused to fetch metadata from https://acme.test: "
            "not an http(s) URL with a host (scheme 'ftp')",
        )

    def test_timeout(self, dns, web, og_log):
        dns.records["acme.test"] = [PUBLIC_IP]
        web.routes["acme.test/in/jane-doe"] = fails_with(httpx.ReadTimeout("timed out"))

        fetch(PERSONAL_URL)

        assert_logged_without_path_or_query(
            og_log, "Timeout fetching metadata from https://acme.test"
        )

    def test_other_error_logs_its_type_only(self, dns, web, og_log):
        """A library's error message can repeat the URL."""
        dns.records["acme.test"] = [PUBLIC_IP]
        web.routes["acme.test/in/jane-doe"] = fails_with(
            httpx.ConnectError(f"cannot reach {PERSONAL_URL}")
        )

        fetch(PERSONAL_URL)

        assert_logged_without_path_or_query(
            og_log, "Error fetching metadata from https://acme.test: ConnectError"
        )

    def test_preview_endpoint_guard(
        self, client: TestClient, auth_headers: dict, caplog, monkeypatch
    ):
        """The endpoint's own guard, for a fetcher that raises instead of returning."""
        from server.app import urls

        async def broken_fetcher(url, timeout=5):
            raise RuntimeError("fetcher bug")

        monkeypatch.setattr(urls, "fetch_opengraph_metadata", broken_fetcher)
        caplog.set_level(logging.WARNING, logger="server.app.urls")

        r = client.post(
            "/api/v1/urls/fetch-metadata", json={"url": PERSONAL_URL}, headers=auth_headers
        )

        assert r.status_code == 200
        assert_logged_without_path_or_query(
            caplog, "Open Graph lookup failed for https://acme.test"
        )
