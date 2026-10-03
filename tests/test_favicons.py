"""
Phase 8.7 — the destination's icon, from the same fetch as its preview (server/utils/opengraph.py).

- The icon the page declares (`<link rel="icon">`, `rel="shortcut icon"`, `apple-touch-icon`):
  an SVG first, then the PNG with the largest declared `sizes`, then any icon. Relative links
  resolve against the URL the redirects ended on; only http(s) is kept.
- None declared: the origin's `/favicon.ico`, when one request there, through the SSRF guard,
  answers 200 with an image.
- og:image resolves the same way, and `fetched` tells an answer (a 404 included) from a failure.

No network: the `dns` and `web` fixtures of tests/test_opengraph_ssrf.py stand in for it.
"""

import asyncio

import httpx
import pytest

from server.core.config import settings
from server.utils.opengraph import fetch_opengraph_metadata
from tests import test_opengraph_ssrf as ssrf

PUBLIC_IP = ssrf.PUBLIC_IP
OTHER_PUBLIC_IP = ssrf.OTHER_PUBLIC_IP

dns = ssrf.dns
web = ssrf.web


@pytest.fixture(autouse=True)
def guard_on(monkeypatch):
    monkeypatch.setattr(settings, "og_fetch_allow_private", False)


def fetch(url: str):
    return asyncio.run(fetch_opengraph_metadata(url))


def html_page(head: str, status: int = 200):
    return lambda request: httpx.Response(status, html=f"<html><head>{head}</head></html>")


def icon(content_type: str = "image/x-icon", status: int = 200):
    return lambda request: httpx.Response(status, headers={"content-type": content_type})


@pytest.fixture
def site(dns, web):
    dns.records["example.com"] = [PUBLIC_IP]
    return web


def _paths(web) -> list[str]:
    return [request.url.path for request in web.requests]


class TestTheDeclaredIcon:
    def test_an_svg_first(self, site):
        site.routes["example.com/"] = html_page(
            '<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">'
            '<link rel="apple-touch-icon" href="/apple.png" sizes="180x180">'
            '<link rel="icon" href="/favicons/favicon.svg" type="image/svg+xml">'
        )

        assert fetch("https://example.com/").favicon_url == (
            "https://example.com/favicons/favicon.svg"
        )
        assert _paths(site) == ["/"]  # declared: no /favicon.ico request

    def test_an_svg_by_its_extension(self, site):
        site.routes["example.com/"] = html_page(
            '<link rel="icon" href="/a.png" sizes="64x64"><link rel="icon" href="/b.svg">'
        )

        assert fetch("https://example.com/").favicon_url == "https://example.com/b.svg"

    def test_then_the_largest_declared_png(self, site):
        site.routes["example.com/"] = html_page(
            '<link rel="shortcut icon" href="/favicon.ico">'
            '<link rel="icon" href="/16.png" sizes="16x16" type="image/png">'
            '<link rel="apple-touch-icon" href="/180.png" sizes="180x180">'
            '<link rel="icon" href="/multi.png" sizes="32x32 48x48" type="image/png">'
        )

        assert fetch("https://example.com/").favicon_url == "https://example.com/180.png"

    def test_then_any_icon_the_first_one(self, site):
        site.routes["example.com/"] = html_page(
            '<link rel="stylesheet" href="/site.css">'
            '<link rel="SHORTCUT ICON" href="/static/fav.ico">'
            '<link rel="icon" href="/other.ico">'
        )

        assert fetch("https://example.com/").favicon_url == "https://example.com/static/fav.ico"

    def test_safaris_mask_icon_isnt_one(self, site):
        site.routes["example.com/"] = html_page('<link rel="mask-icon" href="/pinned.svg">')
        site.routes["example.com/favicon.ico"] = icon()

        assert fetch("https://example.com/").favicon_url == "https://example.com/favicon.ico"

    def test_relative_to_where_the_redirects_ended(self, dns, site):
        dns.records["www.example.org"] = [OTHER_PUBLIC_IP]
        site.routes["example.com/go"] = ssrf.redirect("https://www.example.org/en/home")
        site.routes["www.example.org/en/home"] = html_page(
            '<link rel="icon" href="img/icon.svg"><meta property="og:image" content="/share.png">'
        )

        metadata = fetch("https://example.com/go")

        assert metadata.favicon_url == "https://www.example.org/en/img/icon.svg"
        assert metadata.image_url == "https://www.example.org/share.png"

    def test_a_protocol_relative_link(self, site):
        site.routes["example.com/"] = html_page('<link rel="icon" href="//cdn.example.net/i.svg">')

        assert fetch("https://example.com/").favicon_url == "https://cdn.example.net/i.svg"

    @pytest.mark.parametrize(
        "href", ["data:image/png;base64,iVBORw0KGgo=", "javascript:alert(1)", "   "]
    )
    def test_only_http_links(self, site, href):
        site.routes["example.com/"] = html_page(f'<link rel="icon" href="{href}">')

        assert fetch("https://example.com/").favicon_url is None  # and no /favicon.ico there

    def test_a_non_http_og_image_is_dropped(self, site):
        site.routes["example.com/"] = html_page(
            '<link rel="icon" href="/i.svg"><meta property="og:image" content="data:image/png,x">'
        )

        assert fetch("https://example.com/").image_url is None


class TestTheOriginsFaviconIco:
    def test_used_when_it_answers_200_with_an_image(self, site):
        site.routes["example.com/article"] = html_page('<meta property="og:title" content="A">')
        site.routes["example.com/favicon.ico"] = icon("image/vnd.microsoft.icon")

        metadata = fetch("https://example.com/article")

        assert metadata.favicon_url == "https://example.com/favicon.ico"
        assert _paths(site) == ["/article", "/favicon.ico"]  # one request

    def test_the_links_own_origin_first(self, dns, site):
        """drive.google.com sends a stranger to accounts.google.com's sign-in page, which
        declares no icon: the link is Drive's, and so is its icon."""
        dns.records["accounts.example.org"] = [OTHER_PUBLIC_IP]
        site.routes["example.com/file/d/1"] = ssrf.redirect("https://accounts.example.org/signin")
        site.routes["accounts.example.org/signin"] = html_page("")
        site.routes["example.com/favicon.ico"] = icon()
        site.routes["accounts.example.org/favicon.ico"] = icon()

        assert fetch("https://example.com/file/d/1").favicon_url == (
            "https://example.com/favicon.ico"
        )
        assert [r.headers["host"] + r.url.path for r in site.requests][-1] == (
            "example.com/favicon.ico"
        )

    def test_then_the_origin_the_redirects_ended_on(self, dns, site):
        dns.records["www.example.org"] = [OTHER_PUBLIC_IP]
        site.routes["example.com/go"] = ssrf.redirect("https://www.example.org/page")
        site.routes["www.example.org/page"] = html_page("")
        site.routes["www.example.org/favicon.ico"] = icon()

        assert fetch("https://example.com/go").favicon_url == "https://www.example.org/favicon.ico"

    def test_once_per_origin(self, site):
        site.routes["example.com/old"] = ssrf.redirect("/new")
        site.routes["example.com/new"] = html_page("")

        assert fetch("https://example.com/old").favicon_url is None
        assert _paths(site) == ["/old", "/new", "/favicon.ico"]

    def test_none_when_its_a_404(self, site):
        """griddo.io's case, had it declared nothing: no /favicon.ico there."""
        site.routes["example.com/"] = html_page("")

        assert fetch("https://example.com/").favicon_url is None

    def test_none_when_it_isnt_an_image(self, site):
        """A site that answers every path with its home page isn't serving an icon."""
        site.routes["example.com/"] = html_page("")
        site.routes["example.com/favicon.ico"] = icon("text/html; charset=utf-8")

        assert fetch("https://example.com/").favicon_url is None

    def test_through_the_guard(self, site):
        site.routes["example.com/"] = html_page("")
        site.routes["example.com/favicon.ico"] = ssrf.redirect("http://169.254.169.254/icon")

        assert fetch("https://example.com/").favicon_url is None
        assert _paths(site) == ["/", "/favicon.ico"]  # the internal address never asked

    def test_tried_for_a_page_that_isnt_html(self, site):
        site.routes["example.com/report.pdf"] = lambda r: httpx.Response(
            200, headers={"content-type": "application/pdf"}
        )
        site.routes["example.com/favicon.ico"] = icon()

        assert fetch("https://example.com/report.pdf").favicon_url == (
            "https://example.com/favicon.ico"
        )

    def test_a_failed_icon_request_keeps_the_preview(self, site):
        def boom(request):
            raise httpx.ConnectError("reset", request=request)

        site.routes["example.com/"] = html_page('<meta property="og:title" content="Kept">')
        site.routes["example.com/favicon.ico"] = boom

        metadata = fetch("https://example.com/")

        assert (metadata.title, metadata.favicon_url) == ("Kept", None)


class TestFetched:
    """Whether the page answered: a refresh only replaces what a link knows when it did."""

    def test_a_page_with_a_preview(self, site):
        site.routes["example.com/"] = html_page('<meta property="og:title" content="A">')

        assert fetch("https://example.com/").fetched is True

    def test_a_404_answered_with_nothing(self, site):
        assert fetch("https://example.com/gone").fetched is True

    def test_a_5xx_didnt(self, site):
        site.routes["example.com/"] = lambda r: httpx.Response(503)

        assert fetch("https://example.com/").fetched is False

    def test_a_refused_one_didnt(self, dns, web):
        assert fetch("http://169.254.169.254/").fetched is False
        assert web.requests == []  # and no /favicon.ico either

    def test_a_timeout_didnt(self, site):
        def slow(request):
            raise httpx.ReadTimeout("slow", request=request)

        site.routes["example.com/"] = slow

        assert fetch("https://example.com/").fetched is False
        assert _paths(site) == ["/"]
