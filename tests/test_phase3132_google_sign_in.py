"""
Phase 3.13.2 — sign in with Google, against a fake Google (tests/fake_google.py).

The browser goes to /google/start, Google sends it back to /google/callback, and
the callback hands the frontend a one-time code, which the page trades for a JWT
at /google/exchange. The JWT never travels in a URL.
"""

import base64
import hashlib
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from alembic import command
from jose import jwt
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from main import app
from server.app.google_auth import get_google_http
from server.core.auth import hash_password
from server.core.config import settings
from server.core.models import (
    GoogleAuthState,
    LoginCode,
    OrganizationMember,
    OrgRole,
    User,
    UserIdentity,
)
from server.utils.google_oidc import GoogleHttp
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, FakeGoogle

REDIRECT_URI = "https://testserver/api/v1/auth/google/callback"
FRONTEND_URL = "https://app.shurly.test"
GOOGLE_CODE = "4/fake-authorization-code"
_PASSWORD_HASH = hash_password("pre-registered-1")


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(settings, "google_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "google_client_secret", SecretStr(CLIENT_SECRET))
    monkeypatch.setattr(settings, "google_redirect_uri", REDIRECT_URI)
    monkeypatch.setattr(settings, "frontend_url", FRONTEND_URL)
    monkeypatch.setattr(settings, "organization_domain", "griddo.io")
    http = GoogleHttp(fake.http())
    app.dependency_overrides[get_google_http] = lambda: http
    yield fake
    app.dependency_overrides.pop(get_google_http, None)


@pytest.fixture
def browser(client, google):
    """The test client as a browser: on HTTPS (the state cookie is Secure), and
    not following the redirect to Google."""
    client.base_url = "https://testserver"
    client.follow_redirects = False
    return client


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def _start(browser) -> str:
    """Start a sign-in; returns the `state` sent to Google."""
    response = browser.get("/api/v1/auth/google/start")
    assert response.status_code == 302
    return _query(response.headers["location"])["state"]


def _callback(browser, state: str | None, **params):
    params = {"code": GOOGLE_CODE, "state": state, **params}
    return browser.get(
        "/api/v1/auth/google/callback", params={k: v for k, v in params.items() if v is not None}
    )


def _landing(response) -> dict[str, str]:
    """Where the callback sent the browser: the frontend's /login/ page, and its fragment."""
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{FRONTEND_URL}/login/"
    assert not location.query
    return {k: v[0] for k, v in parse_qs(location.fragment).items()}


def _sign_in(browser) -> dict[str, str]:
    return _landing(_callback(browser, _start(browser)))


def _exchange(browser, code: str):
    return browser.post("/api/v1/auth/google/exchange", json={"code": code})


def _token(browser) -> str:
    """A full sign-in, down to the JWT."""
    response = _exchange(browser, _sign_in(browser)["code"])
    assert response.status_code == 200
    return response.json()["access_token"]


def _me(browser, token: str):
    return browser.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})


def _events(capsys, name: str) -> list[dict]:
    import json

    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


def _person(db, email="ana@griddo.io", **fields) -> User:
    """An account made before Google: by the open sign-up, with a password."""
    user = User(email=email, password_hash=_PASSWORD_HASH, **{"is_active": True, **fields})
    db.add(user)
    db.commit()
    return user


class TestConfiguration:
    @pytest.mark.parametrize("path", ["start", "callback"])
    def test_unconfigured_the_browser_goes_back_to_the_frontend(self, client, monkeypatch, path):
        """Full-page navigations: a JSON 503 would show the person raw JSON."""
        monkeypatch.setattr(settings, "frontend_url", FRONTEND_URL)

        response = client.get(f"/api/v1/auth/google/{path}", follow_redirects=False)

        assert _landing(response) == {"error": "google_unavailable"}

    @pytest.mark.parametrize("path", ["start", "callback"])
    def test_unconfigured_without_a_frontend_it_answers_503(self, client, path):
        response = client.get(f"/api/v1/auth/google/{path}", follow_redirects=False)

        assert response.status_code == 503
        assert "isn't configured" in response.json()["detail"]

    def test_an_empty_organization_domain_counts_as_unconfigured(self, browser, monkeypatch):
        """Otherwise any Google account, Gmail included, could sign in."""
        monkeypatch.setattr(settings, "organization_domain", "")

        response = browser.get("/api/v1/auth/google/start")

        assert _landing(response) == {"error": "google_unavailable"}


class TestStart:
    def test_sends_the_browser_to_google(self, browser):
        response = browser.get("/api/v1/auth/google/start")

        location = urlsplit(response.headers["location"])
        query = _query(response.headers["location"])
        assert f"{location.scheme}://{location.netloc}{location.path}" == (
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
        assert query["response_type"] == "code"
        assert query["client_id"] == CLIENT_ID
        assert query["redirect_uri"] == REDIRECT_URI
        assert set(query["scope"].split()) == {"openid", "email"}
        assert query["code_challenge_method"] == "S256"
        assert query["code_challenge"]
        assert query["hd"] == "griddo.io"
        assert query["state"]

    def test_binds_the_state_to_this_browser(self, browser):
        response = browser.get("/api/v1/auth/google/start")
        state = _query(response.headers["location"])["state"]

        cookie = response.headers["set-cookie"]
        assert cookie.startswith(f"shurly_google_state={state};")
        attributes = {part.strip().lower() for part in cookie.split(";")[1:]}
        assert {"httponly", "secure", "samesite=lax", "path=/api/v1/auth/google"} <= attributes

    def test_the_state_is_stored_hashed(self, browser, db_session):
        state = _start(browser)

        (row,) = db_session.query(GoogleAuthState).all()
        assert row.state_hash == hashlib.sha256(state.encode()).hexdigest()

    def test_expired_sign_ins_are_purged(self, browser, db_session):
        _start(browser)
        db_session.query(GoogleAuthState).update(
            {GoogleAuthState.expires_at: datetime.utcnow() - timedelta(seconds=1)}
        )
        db_session.commit()

        _start(browser)

        assert db_session.query(GoogleAuthState).count() == 1


class TestState:
    def test_missing_state_is_refused(self, browser, db_session):
        _start(browser)

        assert _landing(_callback(browser, None))["error"] == "state"
        assert db_session.query(User).count() == 0

    def test_another_sign_ins_state_is_refused(self, browser):
        """Two tabs: the cookie holds the newer state."""
        first = _start(browser)
        _start(browser)

        assert _landing(_callback(browser, first))["error"] == "state"

    def test_a_state_without_the_cookie_is_refused(self, browser):
        """A link to the callback, sent to someone else's browser (login CSRF)."""
        state = _start(browser)
        browser.cookies.clear()

        assert _landing(_callback(browser, state))["error"] == "state"

    def test_a_state_works_once(self, browser):
        state = _start(browser)
        assert "code" in _landing(_callback(browser, state))

        replay = browser.get(
            "/api/v1/auth/google/callback",
            params={"code": GOOGLE_CODE, "state": state},
            headers={"Cookie": f"shurly_google_state={state}"},
        )

        assert _landing(replay)["error"] == "state"

    def test_an_expired_state_is_refused(self, browser, db_session):
        state = _start(browser)
        db_session.query(GoogleAuthState).update(
            {GoogleAuthState.expires_at: datetime.utcnow() - timedelta(seconds=1)}
        )
        db_session.commit()

        assert _landing(_callback(browser, state))["error"] == "state"

    def test_the_callback_clears_the_cookie(self, browser):
        response = _callback(browser, _start(browser))

        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith('shurly_google_state="";') or "max-age=0" in cookie
        assert "path=/api/v1/auth/google" in cookie

    def test_cancelled_at_google(self, browser, google, db_session):
        state = _start(browser)

        response = _callback(browser, state, code=None, error="access_denied")

        assert _landing(response)["error"] == "denied"
        assert google.token_requests == []
        assert db_session.query(User).count() == 0


class TestGoogle:
    def test_the_code_is_redeemed_with_the_pkce_verifier(self, browser, google):
        response = browser.get("/api/v1/auth/google/start")
        query = _query(response.headers["location"])

        _callback(browser, query["state"])

        (request,) = google.token_requests
        digest = hashlib.sha256(request["code_verifier"].encode()).digest()
        assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == query["code_challenge"]
        assert request["grant_type"] == "authorization_code"
        assert request["code"] == GOOGLE_CODE
        assert request["redirect_uri"] == REDIRECT_URI
        assert (request["client_id"], request["client_secret"]) == (CLIENT_ID, CLIENT_SECRET)

    def test_unreachable(self, browser, google):
        google.unreachable = True

        assert _sign_in(browser)["error"] == "google_unavailable"

    def test_google_refuses_the_code(self, browser, google, capsys):
        google.token_error = "invalid_grant"

        assert _sign_in(browser)["error"] == "invalid_token"
        (event,) = _events(capsys, "auth.google_refused")
        assert (event["reason"], event["google_error"]) == ("invalid_token", "invalid_grant")

    def test_the_signing_certs_are_cached_as_google_allows(self, browser, google):
        google.cache_control = "public, max-age=3600, must-revalidate, no-transform"

        _sign_in(browser)
        _sign_in(browser)

        assert google.cert_fetches == 1

    def test_without_caching_headers_the_certs_are_fetched_each_time(self, browser, google):
        _sign_in(browser)
        _sign_in(browser)

        assert google.cert_fetches == 2


class TestIdToken:
    """google-auth checks the signature, aud, iss and exp; hd and email_verified are ours."""

    @pytest.mark.parametrize("hd", ["gmail.com", "evilgriddo.io", None])
    def test_only_the_organizations_workspace_gets_in(self, browser, google, db_session, hd):
        """`hd` sent to Google is only a hint: the token's `hd` is what counts."""
        google.claims["hd"] = hd

        assert _sign_in(browser)["error"] == "domain"
        assert db_session.query(User).count() == 0

    @pytest.mark.parametrize("verified", [False, None, "true"])
    def test_the_address_must_be_verified(self, browser, google, db_session, verified):
        google.claims["email_verified"] = verified

        assert _sign_in(browser)["error"] == "unverified"
        assert db_session.query(User).count() == 0

    @pytest.mark.parametrize(
        ("claim", "value"),
        [
            ("aud", "someone-else.apps.googleusercontent.com"),
            ("iss", "https://accounts.evil.test"),
            ("exp", int(time.time()) - 60),
        ],
    )
    def test_a_token_for_someone_else_or_expired_is_refused(
        self, browser, google, db_session, claim, value
    ):
        google.claims[claim] = value

        assert _sign_in(browser)["error"] == "invalid_token"
        assert db_session.query(User).count() == 0

    @pytest.mark.parametrize("signing", ["other_key", "none"])
    def test_a_token_google_did_not_sign_is_refused(self, browser, google, db_session, signing):
        google.signing = signing

        assert _sign_in(browser)["error"] == "invalid_token"
        assert db_session.query(User).count() == 0


class TestAccounts:
    def test_the_first_sign_in_makes_the_account_and_joins_the_organization(
        self, browser, db_session
    ):
        token = _token(browser)

        user = db_session.query(User).one()
        assert (user.email, user.password_hash) == ("ana@griddo.io", None)
        identity = db_session.query(UserIdentity).one()
        assert (identity.user_id, identity.provider, identity.subject, identity.email) == (
            user.id,
            "google",
            "1001",
            "ana@griddo.io",
        )
        membership = db_session.query(OrganizationMember).filter_by(user_id=user.id).one()
        assert membership.role == OrgRole.MEMBER
        me = _me(browser, token).json()
        assert (me["email"], me["has_google"], me["has_password"]) == (
            "ana@griddo.io",
            True,
            False,
        )

    def test_an_address_off_the_organizations_domain_joins_nothing(
        self, browser, google, db_session
    ):
        """Same Workspace (hd), another of its domains: the 3.14.2 domain gate still applies."""
        google.claims["email"] = "ana@griddo.com"

        _token(browser)

        user = db_session.query(User).one()
        assert db_session.query(OrganizationMember).filter_by(user_id=user.id).count() == 0

    def test_later_sign_ins_match_by_sub_even_after_an_email_change(
        self, browser, google, db_session
    ):
        _token(browser)
        google.claims["email"] = "ana.garcia@griddo.io"

        token = _token(browser)

        user = db_session.query(User).one()
        assert user.email == "ana@griddo.io"  # the JWT's subject; stays
        assert db_session.query(UserIdentity).one().email == "ana.garcia@griddo.io"
        assert _me(browser, token).json()["id"] == str(user.id)

    def test_a_different_google_account_never_takes_over_a_linked_one(
        self, browser, google, db_session, capsys
    ):
        """Google may give a freed address to someone else: a new `sub` isn't Ana."""
        _token(browser)
        ana = db_session.query(User).one()
        google.claims["sub"] = "2002"
        capsys.readouterr()

        assert _sign_in(browser)["error"] == "account_conflict"

        assert db_session.query(UserIdentity).one().subject == "1001"
        (event,) = _events(capsys, "auth.google_refused")
        assert (event["reason"], event["user_id"]) == ("account_conflict", str(ana.id))

    def test_an_account_made_before_google_is_linked_and_its_maker_locked_out(
        self, browser, db_session, capsys
    ):
        """Account pre-hijacking: someone registered ana@ with a password before Ana
        signed in with Google. Their password, API key and sessions stop working."""
        user = _person(db_session, api_key="k" * 43)
        # From an earlier second: tokens from the cutoff's own second are kept.
        issued = datetime.utcnow() - timedelta(hours=1)
        old_session = jwt.encode(
            {"sub": user.email, "iat": issued, "exp": issued + timedelta(days=7)},
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )
        assert _me(browser, old_session).status_code == 200
        capsys.readouterr()

        token = _token(browser)

        db_session.refresh(user)
        assert db_session.query(User).count() == 1
        assert db_session.query(UserIdentity).one().user_id == user.id
        assert (user.password_hash, user.api_key) == (None, None)
        assert _me(browser, old_session).status_code == 401
        assert _me(browser, "k" * 43).status_code == 401
        assert _me(browser, token).status_code == 200
        login = browser.post(
            "/api/v1/auth/login", json={"email": "ana@griddo.io", "password": "pre-registered-1"}
        )
        assert login.status_code == 401
        (event,) = _events(capsys, "auth.identity_linked")
        assert event == {
            "ts": event["ts"],
            "event": "auth.identity_linked",
            "user_id": str(user.id),
            "provider": "google",
            "password_cleared": True,
            "api_key_revoked": True,
        }

    def test_the_email_match_ignores_case(self, browser, db_session):
        user = _person(db_session, email="Ana@Griddo.io")

        _token(browser)

        assert db_session.query(UserIdentity).one().user_id == user.id

    def test_a_closed_account_is_refused(self, browser, db_session):
        _token(browser)
        db_session.query(User).update({User.is_active: False})
        db_session.commit()

        assert _sign_in(browser)["error"] == "inactive"

    def test_a_closed_account_is_not_linked_either(self, browser, db_session):
        _person(db_session, is_active=False)

        assert _sign_in(browser)["error"] == "inactive"
        assert db_session.query(UserIdentity).count() == 0


class TestLoginCode:
    def test_answers_like_login(self, browser):
        response = _exchange(browser, _sign_in(browser)["code"])

        assert response.status_code == 200
        assert set(response.json()) == {"access_token", "token_type"}
        assert response.json()["token_type"] == "bearer"

    def test_works_once(self, browser):
        code = _sign_in(browser)["code"]
        assert _exchange(browser, code).status_code == 200

        assert _exchange(browser, code).status_code == 400

    def test_lives_60_seconds_at_most(self, browser, db_session):
        _sign_in(browser)

        (row,) = db_session.query(LoginCode).all()
        assert row.expires_at - datetime.utcnow() <= timedelta(seconds=60)

    def test_expires(self, browser, db_session):
        code = _sign_in(browser)["code"]
        db_session.query(LoginCode).update(
            {LoginCode.expires_at: datetime.utcnow() - timedelta(seconds=1)}
        )
        db_session.commit()

        assert _exchange(browser, code).status_code == 400

    def test_is_stored_hashed(self, browser, db_session):
        code = _sign_in(browser)["code"]

        (row,) = db_session.query(LoginCode).all()
        assert row.code_hash == hashlib.sha256(code.encode()).hexdigest()

    def test_an_unknown_code_is_refused(self, browser):
        assert _exchange(browser, "made-up").status_code == 400

    def test_a_closed_account_gets_no_session(self, browser, db_session):
        code = _sign_in(browser)["code"]
        db_session.query(User).update({User.is_active: False})
        db_session.commit()

        assert _exchange(browser, code).status_code == 400

    def test_the_sign_in_is_logged(self, browser, db_session, capsys):
        capsys.readouterr()

        _token(browser)

        user = db_session.query(User).one()
        assert [(e["method"], e["user_id"]) for e in _events(capsys, "auth.login")] == [
            ("google", str(user.id))
        ]


class TestRedirect:
    def test_goes_only_to_the_frontend_url(self, browser):
        """No open redirect: the target never comes from the request."""
        state = _start(browser)

        response = _callback(
            browser, state, next="https://evil.test/", redirect_uri="https://evil.test/"
        )

        assert "code" in _landing(response)

    def test_errors_say_nothing_else(self, browser, google):
        google.claims["hd"] = "gmail.com"

        response = _callback(browser, _start(browser))

        assert urlsplit(response.headers["location"]).fragment == "error=domain"

    def test_nothing_secret_or_personal_reaches_the_log(self, browser, google, capsys):
        capsys.readouterr()
        state = _start(browser)
        landing = _landing(_callback(browser, state))
        token = _exchange(browser, landing["code"]).json()["access_token"]
        _me(browser, token)

        err = capsys.readouterr().err
        secrets = {
            "client secret": CLIENT_SECRET,
            "Google's code": GOOGLE_CODE,
            "state": state,
            "PKCE verifier": google.token_requests[0]["code_verifier"],
            "ID token": google.issued_id_tokens[0],
            "one-time code": landing["code"],
            "JWT": token,
            "email": "ana@griddo.io",
        }
        assert [name for name, value in secrets.items() if value in err] == []


def test_migration_0004_keeps_accounts_and_passwords(pg_engine):
    """Production has data: 0004 only adds, and existing passwords stay."""
    from server.core.migrations import alembic_config

    user_id = "00000000-0000-0000-0000-00000000000b"
    config = alembic_config()
    with pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0003")
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, api_key_scope, is_active, created_at)"
                " VALUES (:id, 'smoke@griddo.io', 'x', 'FULL_ACCESS', true, now())"
            ),
            {"id": user_id},
        )
        command.upgrade(config, "head")

    identity = (
        "INSERT INTO user_identities (id, user_id, provider, subject, email, created_at)"
        " VALUES (gen_random_uuid(), :id, 'google', '1001', 'smoke@griddo.io', now())"
    )
    with pg_engine.begin() as conn:
        row = conn.execute(text("SELECT email, password_hash, sessions_valid_from FROM users"))
        assert row.one() == ("smoke@griddo.io", "x", None)
        conn.execute(text("UPDATE users SET password_hash = NULL"))
        conn.execute(text(identity), {"id": user_id})
    with pytest.raises(IntegrityError), pg_engine.begin() as conn:
        conn.execute(text(identity), {"id": user_id})


def test_migration_0004_downgrades_without_a_usable_blank_password(pg_engine):
    from server.core.auth import verify_password
    from server.core.migrations import alembic_config, run_migrations

    run_migrations(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, api_key_scope, is_active, created_at)"
                " VALUES (gen_random_uuid(), 'g@griddo.io', NULL, 'FULL_ACCESS', true, now())"
            )
        )
        config = alembic_config()
        config.attributes["connection"] = conn
        command.downgrade(config, "0003")
        (password_hash,) = conn.execute(text("SELECT password_hash FROM users")).one()

    assert password_hash
    assert not verify_password("", password_hash)
