"""
Phase 5.8 — MCP clients sign in with Google (fastmcp's OAuth proxy), alongside
API keys and JWTs.
"""

import asyncio
from datetime import datetime, timedelta

import pytest

pytest.importorskip("fastmcp")

from mcp_server.oauth_store import encrypted_database_store  # noqa: E402
from server.core.models import McpOAuthEntry  # noqa: E402
from tests.conftest import TestingSessionLocal  # noqa: E402

SIGNING_KEY = "test-signing-key-0123456789abcdef0123456789abcdef"


class TestStore:
    """The proxy's state in the database, shared by every task and encrypted."""

    @pytest.fixture
    def store(self, db_session):
        return encrypted_database_store(TestingSessionLocal, SIGNING_KEY)

    def test_what_is_put_can_be_read_back(self, store):
        asyncio.run(store.put("k1", {"token": "google-refresh-token"}, collection="c"))

        assert asyncio.run(store.get("k1", collection="c")) == {"token": "google-refresh-token"}

    def test_values_are_encrypted_at_rest(self, store, db_session):
        asyncio.run(store.put("k1", {"token": "google-refresh-token"}, collection="c"))

        (row,) = db_session.query(McpOAuthEntry).all()
        assert (row.collection, row.key) == ("c", "k1")
        assert "google-refresh-token" not in row.value

    def test_another_task_sees_it(self, store):
        """A second store object, as a second task would build it."""
        asyncio.run(store.put("k1", {"v": 1}, collection="c"))

        other = encrypted_database_store(TestingSessionLocal, SIGNING_KEY)

        assert asyncio.run(other.get("k1", collection="c")) == {"v": 1}

    def test_a_second_put_replaces_the_value(self, store, db_session):
        asyncio.run(store.put("k1", {"v": 1}, collection="c"))
        asyncio.run(store.put("k1", {"v": 2}, collection="c"))

        assert asyncio.run(store.get("k1", collection="c")) == {"v": 2}
        assert db_session.query(McpOAuthEntry).count() == 1

    def test_delete(self, store):
        asyncio.run(store.put("k1", {"v": 1}, collection="c"))

        assert asyncio.run(store.delete("k1", collection="c")) is True
        assert asyncio.run(store.get("k1", collection="c")) is None
        assert asyncio.run(store.delete("k1", collection="c")) is False

    def test_expired_entries_read_as_missing_and_go_on_the_next_write(self, store, db_session):
        asyncio.run(store.put("old", {"v": 1}, collection="c", ttl=60))
        db_session.query(McpOAuthEntry).update(
            {McpOAuthEntry.expires_at: datetime.utcnow() - timedelta(seconds=1)}
        )
        db_session.commit()

        assert asyncio.run(store.get("old", collection="c")) is None

        asyncio.run(store.put("new", {"v": 2}, collection="c"))

        assert [row.key for row in db_session.query(McpOAuthEntry).all()] == ["new"]

    def test_a_changed_key_reads_as_missing(self, store):
        """After MCP_OAUTH_SIGNING_KEY changes, clients just sign in again."""
        asyncio.run(store.put("k1", {"v": 1}, collection="c"))

        rotated = encrypted_database_store(TestingSessionLocal, "another-key-" + "x" * 40)

        assert asyncio.run(rotated.get("k1", collection="c")) is None


# --- The sign-in flow, against a fake Google (tests/fake_google.py) ---------------

import base64  # noqa: E402
import hashlib  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import secrets  # noqa: E402
from urllib.parse import parse_qs, urlsplit  # noqa: E402

import httpx2  # noqa: E402  (Starlette's TestClient runs on httpx2)
import jwt as pyjwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from fastmcp.server.auth.jwt_issuer import derive_jwt_key  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from main import create_app  # noqa: E402
from mcp_server import google_oauth  # noqa: E402
from mcp_server.google_oauth import ShurlyGoogleProvider  # noqa: E402
from mcp_server.server import build_mcp_auth  # noqa: E402
from server.core import get_db  # noqa: E402
from server.core.auth import create_access_token, hash_password  # noqa: E402
from server.core.config import settings  # noqa: E402
from server.core.models import OrganizationMember, OrgRole, User, UserIdentity  # noqa: E402
from server.utils.google_oidc import GoogleHttp  # noqa: E402
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, FakeGoogle, FakeUpstream  # noqa: E402

ORIGIN = "https://s.shurly.test"
PUBLIC = f"{ORIGIN}/mcp"
REDIRECT = "http://localhost:3118/callback"
_MCP_HEADERS = {"accept": "application/json, text/event-stream"}


@pytest.fixture
def google(monkeypatch, db_session):
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", SecretStr(CLIENT_SECRET))
    monkeypatch.setattr(settings, "organization_domain", "griddo.io")
    monkeypatch.setattr(settings, "mcp_public_url", PUBLIC)
    monkeypatch.setattr(settings, "mcp_oauth_signing_key", SecretStr(SIGNING_KEY))
    return FakeGoogle()


def _session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _task(google: FakeGoogle):
    """One task: the whole app, its MCP signing in with the fake Google."""

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
    app.dependency_overrides[get_db] = _session
    return app


class _Browser:
    """One browser behind a load balancer with no affinity: each request goes to
    the next task. Cookies are the browser's, whichever task set them."""

    def __init__(self, *apps):
        self._clients = [TestClient(app, base_url=ORIGIN, follow_redirects=False) for app in apps]
        self._next = itertools.cycle(self._clients)
        self.cookies = httpx2.Cookies()

    def __enter__(self):
        for client in self._clients:
            client.__enter__()
        return self

    def __exit__(self, *exc):
        for client in self._clients:
            client.__exit__(*exc)

    def request(self, method: str, url: str, **kwargs):
        client = next(self._next)
        client.cookies = self.cookies
        response = client.request(method, url, **kwargs)
        self.cookies = httpx2.Cookies(client.cookies)
        return response

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)


@pytest.fixture
def browser(google):
    with _Browser(_task(google)) as one_task:
        yield one_task


def _register(browser, redirect_uri: str = REDIRECT):
    return browser.post(
        "/mcp/register",
        json={
            "client_name": "Claude Code",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )


def _sign_in(browser):
    """The whole dance, as Claude Code does it. Returns the /mcp/token response,
    and the client's id."""
    client_id = _register(browser).json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

    authorize = browser.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
            "resource": f"{PUBLIC}/",
        },
    )
    consent = browser.get(authorize.headers["location"])
    form = {
        name: re.search(rf'name="{name}" value="([^"]+)"', consent.text)[1]
        for name in ("txn_id", "csrf_token")
    }
    to_google = browser.post("/mcp/consent", data={**form, "action": "approve"})
    assert to_google.headers["location"].startswith("https://accounts.google.com/")
    state = parse_qs(urlsplit(to_google.headers["location"]).query)["state"][0]
    back = browser.get("/mcp/auth/callback", params={"code": "4/google-code", "state": state})
    assert back.headers["location"].startswith(REDIRECT)
    code = parse_qs(urlsplit(back.headers["location"]).query)["code"][0]
    response = browser.post(
        "/mcp/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    return response, client_id


def _tokens(browser) -> dict:
    response, client_id = _sign_in(browser)
    assert response.status_code == 200, response.text
    return {**response.json(), "client_id": client_id}


def _refresh(browser, tokens: dict):
    return browser.post(
        "/mcp/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": tokens["client_id"],
        },
    )


def _refused(response) -> str:
    """No token: invalid_grant, which fastmcp answers with 401 (the MCP spec's rule
    for invalid tokens) rather than OAuth's 400. Returns the description."""
    assert response.status_code == 401, response.text
    assert response.json()["error"] == "invalid_grant"
    return response.json()["error_description"]


def _mcp(browser, token: str, method: str = "tools/list", params: dict | None = None):
    return browser.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={**_MCP_HEADERS, "authorization": f"Bearer {token}"},
    )


def _result(response) -> dict:
    data = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
    return json.loads(data)["result"]


def _me_through_the_mcp(browser, token: str) -> dict:
    """An auto-generated tool: the MCP calls the API with the caller's credentials."""
    response = _mcp(
        browser, token, "tools/call", {"name": "get_current_user_info", "arguments": {}}
    )
    assert response.status_code == 200, response.text
    return json.loads(_result(response)["content"][0]["text"])


def _events(capsys, name: str) -> list[dict]:
    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


class TestDiscovery:
    def test_the_resource_metadata_names_the_mcp_and_its_authorization_server(self, browser):
        response = browser.get("/.well-known/oauth-protected-resource/mcp/")

        assert response.status_code == 200
        assert response.json()["resource"] == f"{PUBLIC}/"
        assert response.json()["authorization_servers"] == [PUBLIC]

    @pytest.mark.parametrize(
        "path",
        ["/.well-known/oauth-authorization-server/mcp", "/.well-known/openid-configuration/mcp"],
    )
    def test_the_authorization_server_metadata_is_where_clients_look(self, browser, path):
        metadata = browser.get(path).json()

        assert metadata["issuer"] == PUBLIC
        assert metadata["authorization_endpoint"] == f"{PUBLIC}/authorize"
        assert metadata["token_endpoint"] == f"{PUBLIC}/token"
        assert metadata["registration_endpoint"] == f"{PUBLIC}/register"
        assert "S256" in metadata["code_challenge_methods_supported"]

    def test_a_request_without_a_token_is_told_where_the_metadata_is(self, browser):
        response = browser.post("/mcp/", json={}, headers=_MCP_HEADERS)

        assert response.status_code == 401
        assert (
            f'resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp/"'
            in response.headers["www-authenticate"]
        )

    def test_without_the_settings_there_is_nothing_to_discover(self, client):
        assert client.get("/.well-known/oauth-protected-resource/mcp/").status_code == 404


class TestRegistration:
    """Only the MCP clients we target can register: a stranger's app can't ask a
    Griddo person to consent (consent phishing)."""

    @pytest.mark.parametrize(
        "redirect_uri",
        [
            "https://claude.ai/api/mcp/auth_callback",
            "https://claude.com/api/mcp/auth_callback",
            "http://localhost:54321/callback",
            "http://127.0.0.1:8080/callback",
        ],
    )
    def test_claude_and_loopback_clients_register(self, browser, redirect_uri):
        assert _register(browser, redirect_uri).status_code == 201

    @pytest.mark.parametrize(
        "redirect_uri",
        [
            "https://evil.test/callback",
            "https://claude.ai.evil.test/api/mcp/auth_callback",
            "https://claude.ai/somewhere/else",
            "http://localhost.evil.test/callback",
        ],
    )
    def test_any_other_redirect_uri_is_refused(self, browser, redirect_uri):
        assert _register(browser, redirect_uri).status_code == 400


class TestTokens:
    def test_a_google_sign_in_gets_a_token_the_mcp_takes(self, browser):
        token = _tokens(browser)["access_token"]

        response = _mcp(browser, token)

        assert response.status_code == 200
        assert any(tool["name"] == "list_urls" for tool in _result(response)["tools"])

    def test_the_tools_act_as_the_google_account(self, browser):
        """The auto-generated tools call the API with a short-lived JWT for the account."""
        token = _tokens(browser)["access_token"]

        assert _me_through_the_mcp(browser, token)["email"] == "ana@griddo.io"

    def test_the_proxys_token_is_no_api_credential(self, browser):
        token = _tokens(browser)["access_token"]

        response = browser.get("/api/v1/auth/me", headers={"authorization": f"Bearer {token}"})

        assert response.status_code == 401

    def test_api_keys_keep_working_next_to_oauth(self, browser, db_session):
        """Claude Code with --header "Authorization: Bearer <api key>", unchanged."""
        user = User(email="k@griddo.io", is_active=True)
        user.set_api_key("k" * 43)
        db_session.add(user)
        db_session.commit()

        assert _mcp(browser, "k" * 43).status_code == 200
        assert _me_through_the_mcp(browser, "k" * 43)["email"] == "k@griddo.io"

    def test_jwts_too(self, browser, db_session):
        db_session.add(User(email="j@griddo.io", is_active=True))
        db_session.commit()

        assert _mcp(browser, create_access_token(data={"sub": "j@griddo.io"})).status_code == 200


class TestAccounts:
    """The web's rules (server/utils/google_sign_in.py), applied when the client
    redeems its code: a refusal means no token."""

    def test_the_first_sign_in_makes_the_account_and_joins_the_organization(
        self, browser, db_session, capsys
    ):
        capsys.readouterr()

        _tokens(browser)

        user = db_session.query(User).one()
        assert (user.email, user.password_hash) == ("ana@griddo.io", None)
        assert db_session.query(UserIdentity).one().subject == "1001"
        membership = db_session.query(OrganizationMember).filter_by(user_id=user.id).one()
        assert membership.role == OrgRole.MEMBER
        (login,) = _events(capsys, "auth.login")
        assert (login["method"], login["surface"], login["user_id"]) == (
            "google",
            "mcp",
            str(user.id),
        )

    def test_an_account_made_before_google_is_linked_and_its_maker_locked_out(
        self, browser, db_session
    ):
        user = User(
            email="ana@griddo.io",
            password_hash=hash_password("pre-registered-1"),
            is_active=True,
        )
        user.set_api_key("k" * 43)
        db_session.add(user)
        db_session.commit()

        _tokens(browser)

        db_session.refresh(user)
        assert (user.password_hash, user.api_key_hash, user.api_key_prefix) == (None, None, None)
        assert user.sessions_valid_from is not None

    @pytest.mark.parametrize(
        ("claim", "value"), [("hd", "gmail.com"), ("hd", None), ("email_verified", False)]
    )
    def test_accounts_outside_the_workspace_get_no_token(
        self, browser, google, db_session, claim, value
    ):
        google.claims[claim] = value

        response, _ = _sign_in(browser)

        _refused(response)
        assert db_session.query(User).count() == 0

    def test_a_closed_account_gets_no_token(self, browser, db_session):
        db_session.add(User(email="ana@griddo.io", is_active=False))
        db_session.commit()

        response, _ = _sign_in(browser)

        assert _refused(response) == "This Shurly account is closed."

    def test_closing_the_account_ends_access_at_once(self, browser, db_session):
        """Even while Google's answer for the token is still cached."""
        token = _tokens(browser)["access_token"]
        assert _mcp(browser, token).status_code == 200

        db_session.query(User).update({User.is_active: False})
        db_session.commit()

        assert _mcp(browser, token).status_code == 401

    def test_a_closed_account_cannot_refresh(self, browser, db_session):
        """Its Google tokens stay in the store until they expire, but can't be used."""
        tokens = _tokens(browser)
        db_session.query(User).update({User.is_active: False})
        db_session.commit()

        assert _refused(_refresh(browser, tokens)) == "This Shurly account is closed."


class TestGoogleChecks:
    def test_a_refresh_works_without_a_new_id_token(self, browser):
        """Google needn't send one on a refresh; the account is found by `sub`."""
        tokens = _tokens(browser)

        response = _refresh(browser, tokens)

        assert response.status_code == 200, response.text
        assert _mcp(browser, response.json()["access_token"]).status_code == 200

    def test_googles_answer_is_kept_for_a_minute(self, browser, google):
        token = _tokens(browser)["access_token"]
        calls = google.tokeninfo_calls

        _mcp(browser, token)
        _mcp(browser, token)

        assert google.tokeninfo_calls == calls + 1

    def test_a_suspension_at_google_bites_once_the_answer_expires(
        self, browser, google, monkeypatch
    ):
        monkeypatch.setattr(google_oauth, "_VERIFIED_FOR", 0)
        token = _tokens(browser)["access_token"]
        assert _mcp(browser, token).status_code == 200

        google.suspend("1001")

        assert _mcp(browser, token).status_code == 401


class TestScaleOut:
    """Up to two tasks, no affinity, every deploy replaces them: the state is in the
    database, never in a task."""

    def test_two_tasks_complete_one_sign_in(self, google):
        with _Browser(_task(google), _task(google)) as browser:
            token = _tokens(browser)["access_token"]

            assert _mcp(browser, token).status_code == 200
            assert _mcp(browser, token).status_code == 200

    def test_a_task_started_later_takes_the_tokens(self, browser, google):
        token = _tokens(browser)["access_token"]

        with _Browser(_task(google)) as after_a_deploy:
            assert _mcp(after_a_deploy, token).status_code == 200

    def test_changing_the_signing_key_signs_every_mcp_client_out(
        self, browser, google, monkeypatch
    ):
        token = _tokens(browser)["access_token"]

        monkeypatch.setattr(settings, "mcp_oauth_signing_key", SecretStr("another-" + "k" * 40))
        with _Browser(_task(google)) as other_key:
            assert _mcp(other_key, token).status_code == 401


def test_tokens_are_signed_with_the_mcp_key_not_the_google_secret(browser):
    """A leaked or rotated Google client secret must not forge or end the MCP's tokens.
    fastmcp would otherwise derive the key from that secret."""
    token = _tokens(browser)["access_token"]
    ours = derive_jwt_key(high_entropy_material=SIGNING_KEY, salt="shurly-mcp-oauth-signing")
    from_google_secret = derive_jwt_key(
        high_entropy_material=CLIENT_SECRET, salt="fastmcp-jwt-signing-key"
    )

    pyjwt.decode(token, ours, algorithms=["HS256"], options={"verify_aud": False})
    with pytest.raises(pyjwt.InvalidSignatureError):
        pyjwt.decode(token, from_google_secret, algorithms=["HS256"], options={"verify_aud": False})


def test_the_store_upserts_on_postgresql(pg_engine):
    """PostgreSQL's INSERT … ON CONFLICT, which SQLite's tests don't run."""
    from sqlalchemy.orm import sessionmaker

    from server.core.migrations import run_migrations

    run_migrations(pg_engine)
    store = encrypted_database_store(sessionmaker(bind=pg_engine), SIGNING_KEY)

    asyncio.run(store.put("k1", {"v": 1}, collection="c", ttl=60))
    asyncio.run(store.put("k1", {"v": 2}, collection="c", ttl=60))

    assert asyncio.run(store.get("k1", collection="c")) == {"v": 2}
    assert asyncio.run(store.delete("k1", collection="c")) is True
