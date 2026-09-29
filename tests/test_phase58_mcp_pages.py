"""
Phase 5.8 — the MCP sign-in's pages in Shurly's brand (mcp_server/pages.py): the consent page,
its errors, the errors after Google and "not registered", from server/templates/mcp_consent.html
and mcp_error.html instead of fastmcp's. fastmcp keeps the flow's security: the CSRF token, the
cookies, the redirect checks.

Pinned here through the real flow, so a fastmcp upgrade can't drop any of it silently (the deploy
job resolves the newest fastmcp 4.x, then runs these before it builds the image):
1. the client's name, escaped, or its ID; 2. the verified domain, for a CIMD client only;
3. the exact callback address; 4. the form: a POST to itself with txn_id, csrf_token and submit,
and approve and deny; 5. the flow still works; 6. the client ID and scopes; 7. consent every
time; 8. escaping; 9. our headers and no third-party load on every page; 10. every page ours;
11. fastmcp's renderers are ours where it calls them, and a missing one fails loudly.
"""

import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("fastmcp")

from fastmcp.server.auth import cimd  # noqa: E402
from fastmcp.server.auth.handlers import authorize as fastmcp_authorize  # noqa: E402
from fastmcp.server.auth.oauth_proxy import consent as fastmcp_consent  # noqa: E402
from fastmcp.server.auth.oauth_proxy import proxy as fastmcp_proxy  # noqa: E402

from mcp_server import pages  # noqa: E402
from mcp_server.google_oauth import ShurlyGoogleProvider  # noqa: E402
from mcp_server.server import build_mcp_auth  # noqa: E402
from server.core import get_db  # noqa: E402
from server.utils.google_oidc import GoogleHttp  # noqa: E402
from tests import test_phase58_mcp_oauth as oauth_flow  # noqa: E402
from tests.conftest import TestingSessionLocal  # noqa: E402
from tests.fake_google import FakeUpstream  # noqa: E402
from tests.test_phase58_mcp_oauth import (  # noqa: E402
    ORIGIN,
    REDIRECT,
    _Browser,
    _register,
    _session,
)

# The sign-in flow's fixtures: one browser, and the fake Google behind it.
browser = oauth_flow.browser
google = oauth_flow.google


class _Form(HTMLParser):
    """The consent page's forms, inputs and buttons, whatever the attributes' order."""

    def __init__(self, page: str):
        super().__init__()
        self.forms: list[dict] = []
        self.autofocus = False
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "autofocus" in attrs:
            self.autofocus = True
        if tag == "form":
            self.forms.append({**attrs, "inputs": {}, "buttons": []})
        elif tag == "input" and self.forms and attrs.get("type") == "hidden":
            self.forms[-1]["inputs"][attrs.get("name")] = attrs.get("value")
        elif tag == "button" and self.forms:
            self.forms[-1]["buttons"].append(
                (attrs.get("type", "submit"), attrs.get("name"), attrs.get("value"))
            )


def _authorize(browser, client_id: str, redirect: str = REDIRECT):
    return browser.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect,
            "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
            "code_challenge_method": "S256",
            "state": "client-state",
            "resource": f"{ORIGIN}/mcp/",
        },
    )


def _consent(browser, client_id: str | None = None):
    """A client asks; the consent page the browser lands on, and its transaction id."""
    client_id = client_id or _register(browser).json()["client_id"]
    started = _authorize(browser, client_id)
    assert started.status_code == 302, started.text
    txn_id = parse_qs(urlsplit(started.headers["location"]).query)["txn_id"][0]
    return browser.get(started.headers["location"]), client_id, txn_id


def _answer(browser, page, action: str, **changed):
    (form,) = _Form(page.text).forms
    return browser.post("/mcp/consent", data={**form["inputs"], "action": action, **changed})


def _events(capsys, name: str) -> list[dict]:
    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


# ---------------------------------------------------------------------------
# The consent page
# ---------------------------------------------------------------------------


class TestTheConsentPage:
    def test_what_the_person_must_see(self, browser):
        page, client_id, _ = _consent(browser)

        assert page.status_code == 200
        assert 'data-shurly-page="consent"' in page.text
        assert "Claude Code" in page.text  # the name it registered with
        assert REDIRECT in page.text  # the exact callback
        assert client_id in page.text
        assert "openid" in page.text and "email" in page.text

    def test_the_form_fastmcp_reads(self, browser):
        page, _, txn_id = _consent(browser)

        parsed = _Form(page.text)
        (form,) = parsed.forms
        assert form.get("method", "").lower() == "post"
        assert form.get("action") == ""  # to itself: /mcp/consent
        assert form["inputs"]["txn_id"] == txn_id
        assert form["inputs"]["csrf_token"]
        assert form["inputs"]["submit"] == "true"
        assert sorted(form["buttons"]) == [
            ("submit", "action", "approve"),
            ("submit", "action", "deny"),
        ]
        assert not parsed.autofocus

    def test_a_verified_domain_for_a_client_that_proved_it(self, browser, monkeypatch):
        """claude.ai registers by a Client ID Metadata Document, fetched from its own domain."""
        claude = "https://claude.ai/oauth/mcp-oauth-client-metadata"

        async def fetch(self, client_id_url):
            return cimd.CIMDDocument(
                client_id=client_id_url, client_name="Claude", redirect_uris=[REDIRECT]
            )

        monkeypatch.setattr(cimd.CIMDFetcher, "fetch", fetch)

        page, _, _ = _consent(browser, client_id=claude)

        assert page.status_code == 200, page.text
        assert "claude.ai" in page.text.replace(claude, "")  # the badge, not just the ID
        assert "Claude" in page.text

    def test_a_domain_is_verified_only_when_fastmcp_says_so(self):
        """A client registered by DCR names itself: only a CIMD client's domain is proven."""

        def render(**cimd):
            return pages.consent_page(
                client_id="https://claude.ai/oauth/mcp-oauth-client-metadata",
                redirect_uri=REDIRECT,
                scopes=[],
                txn_id="t",
                csrf_token="k",
                client_name="Claude",
                **cimd,
            )

        unverified = render()
        assert render(is_cimd_client=False, cimd_domain="claude.ai") == unverified
        assert render(is_cimd_client=True, cimd_domain="claude.ai") != unverified

    def test_everything_is_escaped(self, browser):
        name = '<img src=x onerror="alert(1)">'
        client_id = browser.post(
            "/mcp/register",
            json={
                "client_name": name,
                "redirect_uris": [REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        ).json()["client_id"]

        page, _, _ = _consent(browser, client_id=client_id)

        assert "<img src=x" not in page.text
        assert "&lt;img src=x onerror=" in page.text

    def test_a_callback_with_quotes_stays_text(self):
        page = pages.consent_page(
            client_id="c",
            redirect_uri='http://localhost:1/cb?a="b"&c=<d>',
            scopes=[],
            txn_id="t",
            csrf_token="k",
        )

        assert "<d>" not in page and '"b"' not in page
        assert "&lt;d&gt;" in page


class TestTheFlowStillWorks:
    def test_allow_goes_to_google(self, browser):
        page, _, _ = _consent(browser)

        allowed = _answer(browser, page, "approve")

        assert allowed.status_code == 302
        assert allowed.headers["location"].startswith("https://accounts.google.com/")

    def test_deny_goes_back_to_the_client(self, browser):
        page, _, _ = _consent(browser)

        denied = _answer(browser, page, "deny")

        assert denied.status_code == 302
        back = urlsplit(denied.headers["location"])
        assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
        query = parse_qs(back.query)
        assert (query["error"], query["state"]) == (["access_denied"], ["client-state"])
        assert query["iss"]

    def test_a_forged_token_and_a_replay_get_our_error(self, browser, capsys):
        page, _, _ = _consent(browser)
        forged = _answer(browser, page, "approve", csrf_token="forged")
        assert _answer(browser, page, "approve").status_code == 302
        replayed = _answer(browser, page, "approve")

        for refused in (forged, replayed):
            assert refused.status_code == 400
            assert 'data-shurly-page="error"' in refused.text
        reasons = [e["reason"] for e in _events(capsys, "mcp.sign_in_error")]
        assert reasons == ["expired_page", "expired_page"]

    def test_consent_every_time(self, browser):
        """Nothing is remembered: fastmcp's default, require_authorization_consent=True."""
        page, client_id, _ = _consent(browser)
        assert _answer(browser, page, "approve").status_code == 302

        again, _, _ = _consent(browser, client_id=client_id)

        assert again.status_code == 200
        assert 'data-shurly-page="consent"' in again.text
        assert not [name for name in browser.cookies.keys() if "APPROVED" in name]


# ---------------------------------------------------------------------------
# Every page: ours, with our headers, loading nothing from anywhere
# ---------------------------------------------------------------------------


def _every_page(browser) -> dict[str, object]:
    """Each page the sign-in can show, by what it's for."""
    page, client_id, txn_id = _consent(browser)
    shown = {"consent": page}
    shown["no transaction"] = browser.get("/mcp/consent")
    shown["unknown transaction"] = browser.get("/mcp/consent", params={"txn_id": "unknown"})
    shown["forged token"] = _answer(browser, page, "approve", csrf_token="forged")
    shown["no action"] = _answer(browser, page, "")
    with _Browser(browser._clients[0].app) as stranger:  # another browser: no consent cookie
        shown["other browser"] = _answer(stranger, page, "approve")
    shown["unregistered"] = browser.get(
        _authorize(browser, "unregistered-client").url,
        headers={"accept": "text/html"},
    )
    shown["callback without code"] = browser.get("/mcp/auth/callback")
    shown["callback, unknown sign-in"] = browser.get(
        "/mcp/auth/callback", params={"code": "4/c", "state": "unknown"}
    )
    shown["cancelled at Google"] = browser.get(
        "/mcp/auth/callback", params={"error": "access_denied", "state": "unknown"}
    )
    return shown


EXPECTED_STATUS = {
    "consent": 200,
    "no transaction": 400,
    "unknown transaction": 400,
    "forged token": 400,
    "no action": 400,
    "other browser": 403,
    "unregistered": 400,
    "callback without code": 400,
    "callback, unknown sign-in": 400,
    "cancelled at Google": 400,
}


# What fastmcp's own pages say, which ours never do.
FASTMCPS_OWN = (
    "FastMCP",
    "gofastmcp",
    "Application Access Request",
    "Client Not Registered",
    "OAuth Error",
    "Authorization Error",
    "confused deputy",
)


def test_every_page_is_ours_with_our_headers(browser):
    shown = _every_page(browser)

    assert {name: page.status_code for name, page in shown.items()} == EXPECTED_STATUS
    for name, page in shown.items():
        headers = page.headers
        assert headers["content-type"].startswith("text/html"), name
        assert headers["content-security-policy"] == pages.PAGE_HEADERS["Content-Security-Policy"]
        assert "form-action" not in headers["content-security-policy"], name
        assert headers["x-frame-options"] == "DENY", name
        assert headers["cache-control"] == "no-store", name
        assert headers["referrer-policy"] == "no-referrer", name
        assert headers["x-content-type-options"] == "nosniff", name
        assert "data-shurly-page=" in page.text, name
        for fastmcps in FASTMCPS_OWN:
            assert fastmcps not in page.text, (name, fastmcps)
        assert not re.search(r"""(src|href)\s*=\s*["']?https?://(?!.*griddo)""", page.text), name
        assert "<script" not in page.text.lower(), name


def test_the_csp_allows_exactly_the_templates_styles():
    policy = pages.PAGE_HEADERS["Content-Security-Policy"]

    assert policy.startswith("default-src 'none'; style-src 'sha256-")
    assert "img-src data:" in policy and "frame-ancestors 'none'" in policy
    for template in (pages.CONSENT_PAGE, pages.ERROR_PAGE):
        assert pages.style_hash(template) in policy


def test_json_answers_are_left_alone(browser):
    registered = _register(browser)

    assert registered.headers["content-type"].startswith("application/json")
    assert "content-security-policy" not in registered.headers


def test_what_happened_is_logged_and_the_url_never_speaks(browser, capsys):
    """fastmcp puts Google's error_description from the URL on its page: anyone could craft a
    link that shows their words under our domain. Ours shows a reason, never that text."""
    crafted = "Your account is locked: call +1 555 0100"

    page = browser.get(
        "/mcp/auth/callback",
        params={"error": "server_error", "error_description": crafted, "state": "unknown"},
    )

    assert crafted not in page.text and "+1 555" not in page.text
    assert "server_error" in page.text  # Google's code, a known shape
    (event,) = _events(capsys, "mcp.sign_in_error")
    assert (event["reason"], event["google_error"]) == ("google_error", "server_error")


@pytest.mark.parametrize("code", ["<b>x</b>", "x" * 100])
def test_an_odd_google_code_isnt_shown(browser, code):
    page = browser.get("/mcp/auth/callback", params={"error": code, "state": "unknown"})

    assert code not in page.text


def test_a_failed_exchange_with_google_is_generic_and_its_log_line_holds_no_secret(google, capsys):
    secret = "code=4/0AbCdEfGhIjKlMnOpQrStUvWxYz0123456789 refresh_token=1//0gSeCrEtToKeN"

    class Refusing(FakeUpstream):
        async def fetch_token(self, url: str, **params) -> dict:
            raise RuntimeError(f"Google said no: {secret}")

    class Provider(ShurlyGoogleProvider):
        def _create_upstream_oauth_client(self):
            return Refusing(google)

    from main import create_app

    auth = build_mcp_auth(
        session_factory=TestingSessionLocal,
        provider_class=Provider,
        http_client=google.http2(),
        google_http=GoogleHttp(google.http()),
    )
    app = create_app(mcp_auth=auth)
    app.dependency_overrides[get_db] = _session
    with _Browser(app) as browser:
        page, _, _ = _consent(browser)
        to_google = _answer(browser, page, "approve")
        state = parse_qs(urlsplit(to_google.headers["location"]).query)["state"][0]
        capsys.readouterr()

        failed = browser.get("/mcp/auth/callback", params={"code": "4/google", "state": state})

    assert failed.status_code == 500
    assert "Google said no" not in failed.text and "4/0AbCd" not in failed.text
    logged = capsys.readouterr().err
    (event,) = [
        e
        for e in (json.loads(x) for x in logged.splitlines() if x.startswith("{"))
        if e["event"] == "mcp.sign_in_error"
    ]
    assert event["reason"] == "token_exchange"
    assert "4/0AbCd" not in json.dumps(event) and "SeCrEt" not in json.dumps(event)


# ---------------------------------------------------------------------------
# Where fastmcp calls its renderers
# ---------------------------------------------------------------------------


def test_fastmcps_renderers_are_ours_once_the_provider_is_built(browser):
    assert fastmcp_consent.create_consent_html is pages.consent_page
    assert fastmcp_proxy.create_error_html is pages.callback_error_page
    assert fastmcp_authorize.create_unregistered_client_html is pages.unregistered_page
    assert fastmcp_consent.create_secure_html_response is pages.html_response
    assert fastmcp_authorize.create_secure_html_response is pages.html_response


def test_a_renderer_fastmcp_moved_fails_loudly(monkeypatch):
    """An upgrade that renames one would put FastMCP's page back: the app refuses to start."""
    monkeypatch.delattr(fastmcp_consent, "create_consent_html")

    with pytest.raises(RuntimeError, match="create_consent_html"):
        pages.check_fastmcp()


@pytest.mark.parametrize("reason", sorted(pages.REASONS))
def test_each_reason_renders(reason):
    page = pages.error_page(reason)

    assert 'data-shurly-page="error"' in page
