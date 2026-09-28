"""
Phase 3.13.3 — an optional password, set by the account's owner.

- Password endpoints take a signed-in session (a JWT), never an API key: a leaked
  key must not turn into a password.
- Without the current password (the Google path, e.g. a forgotten one), the
  session must be fresh: a stolen 7-day JWT can't mint a password that outlives it.
- Removing the password is refused when it's the account's only way in.
- `sessions_valid_from` ends every JWT issued in an earlier second.
- `POST /auth/register` is gone unless ALLOW_PASSWORD_SIGNUP is on.
"""

import json
from datetime import datetime, timedelta

import pytest
from jose import jwt

from server.core.auth import create_access_token, hash_password, pwd_context
from server.core.config import settings
from server.core.models import User, UserIdentity

_PASSWORD = "old-password-1"
_PASSWORD_HASH = hash_password(_PASSWORD)


def _person(db, email="ana@griddo.io", password=True, google=False) -> User:
    user = User(email=email, password_hash=_PASSWORD_HASH if password else None, is_active=True)
    db.add(user)
    db.flush()
    if google:
        db.add(UserIdentity(user_id=user.id, provider="google", subject="g-" + email, email=email))
    db.commit()
    return user


def _jwt(user: User, issued_at: datetime | None = None) -> str:
    """A JWT for `user`; `issued_at=None` gives today's tokens, with `iat` now."""
    if issued_at is None:
        return create_access_token(data={"sub": user.email})
    claims = {"sub": user.email, "iat": issued_at, "exp": issued_at + timedelta(days=7)}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _legacy_jwt(user: User) -> str:
    """A JWT from before this release: no `iat`."""
    claims = {"sub": user.email, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(claims, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _events(capsys, name: str) -> list[dict]:
    lines = [
        json.loads(line) for line in capsys.readouterr().err.splitlines() if line.startswith("{")
    ]
    return [line for line in lines if line.get("event") == name]


def _set(client, token, **body):
    return client.put("/api/v1/auth/password", json=body, headers=_bearer(token))


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


class TestSessions:
    def test_new_tokens_carry_iat(self, db_session):
        user = _person(db_session)

        claims = jwt.get_unverified_claims(_jwt(user))

        assert isinstance(claims["iat"], int)

    def test_tokens_from_before_the_cutoff_are_refused(self, client, db_session):
        user = _person(db_session)
        token = _jwt(user, issued_at=datetime.utcnow() - timedelta(hours=1))
        user.sessions_valid_from = datetime.utcnow()
        db_session.commit()

        assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401

    def test_a_token_from_the_cutoffs_own_second_is_kept(self, client, db_session):
        """The person whose sign-in set the cutoff keeps the session it gave them."""
        user = _person(db_session)
        now = datetime.utcnow()
        user.sessions_valid_from = now.replace(microsecond=999_999)
        db_session.commit()

        token = _jwt(user, issued_at=now.replace(microsecond=0))

        assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200

    def test_tokens_without_iat_last_until_a_cutoff_is_set(self, client, db_session):
        """So this release logs nobody out."""
        user = _person(db_session)
        token = _legacy_jwt(user)

        assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 200

        user.sessions_valid_from = datetime.utcnow()
        db_session.commit()

        assert client.get("/api/v1/auth/me", headers=_bearer(token)).status_code == 401

    def test_the_mcp_applies_the_same_cutoff(self, db_session):
        pytest.importorskip("fastmcp")
        from mcp_server.auth import _resolve_user_from_token

        user = _person(db_session)
        old = _jwt(user, issued_at=datetime.utcnow() - timedelta(hours=1))
        assert _resolve_user_from_token(db_session, old) is not None

        user.sessions_valid_from = datetime.utcnow()
        db_session.commit()

        assert _resolve_user_from_token(db_session, old) is None
        assert _resolve_user_from_token(db_session, _jwt(user)) is not None


class TestLoginTiming:
    """
    A refused login mustn't reveal whether the address has an account: every one
    runs a bcrypt check, a dummy one when there's no hash to check against. Tested
    by the check running, not by timing it.
    """

    @pytest.fixture
    def dummy_checks(self, monkeypatch) -> list[None]:
        calls = []
        real = pwd_context.dummy_verify
        monkeypatch.setattr(pwd_context, "dummy_verify", lambda: calls.append(None) or real())
        return calls

    def test_an_unknown_address_runs_the_dummy_check(self, client, dummy_checks):
        assert _login(client, "nobody@griddo.io", "whatever-1").status_code == 401

        assert len(dummy_checks) == 1

    def test_an_account_without_a_password_runs_it_too(self, client, db_session, dummy_checks):
        _person(db_session, password=False, google=True)

        assert _login(client, "ana@griddo.io", "whatever-1").status_code == 401

        assert len(dummy_checks) == 1

    def test_a_wrong_password_checks_the_real_hash_instead(self, client, db_session, dummy_checks):
        _person(db_session)

        assert _login(client, "ana@griddo.io", "wrong-password").status_code == 401

        assert dummy_checks == []


class TestLogin:
    def test_an_account_without_a_password_cannot_log_in_with_one(self, client, db_session):
        _person(db_session, password=False, google=True)

        assert _login(client, "ana@griddo.io", "anything-at-all").status_code == 401

    def test_login_is_logged_with_the_method_and_nothing_personal(self, client, db_session, capsys):
        user = _person(db_session)
        capsys.readouterr()

        response = _login(client, "ana@griddo.io", _PASSWORD)

        assert response.status_code == 200
        err = capsys.readouterr().err
        events = [json.loads(line) for line in err.splitlines() if line.startswith("{")]
        logins = [e for e in events if e["event"] == "auth.login"]
        assert [(e["method"], e["user_id"]) for e in logins] == [("password", str(user.id))]
        assert "ana@griddo.io" not in err
        assert response.json()["access_token"] not in err

    def test_a_failed_login_is_not_logged_as_one(self, client, db_session, capsys):
        _person(db_session)
        capsys.readouterr()

        _login(client, "ana@griddo.io", "wrong-password")

        assert _events(capsys, "auth.login") == []


class TestChangePassword:
    def test_without_a_password_it_points_to_setting_one(self, client, db_session):
        user = _person(db_session, password=False, google=True)

        response = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "whatever-1", "new_password": "new-password-1"},
            headers=_bearer(_jwt(user)),
        )

        assert response.status_code == 409
        assert "PUT /api/v1/auth/password" in response.json()["detail"]

    def test_an_api_key_cannot_change_it(self, client, db_session):
        """Not even with the current password: a leaked key must not become a password."""
        user = _person(db_session)
        key = "k" * 43
        user.set_api_key(key)
        db_session.commit()

        response = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": _PASSWORD, "new_password": "new-password-1"},
            headers=_bearer(key),
        )

        assert response.status_code == 403
        assert "API key" in response.json()["detail"]
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200


class TestSetPassword:
    def test_a_google_account_sets_its_first_password(self, client, db_session, capsys):
        user = _person(db_session, password=False, google=True)
        capsys.readouterr()

        response = _set(client, _jwt(user), new_password="new-password-1")

        assert response.status_code == 200
        assert _login(client, "ana@griddo.io", "new-password-1").status_code == 200
        events = _events(capsys, "auth.password_set")
        assert [e["user_id"] for e in events] == [str(user.id)]
        assert set(events[0]) == {"ts", "event", "user_id"}

    def test_forgot_password_sign_in_with_google_and_set_a_new_one(self, client, db_session):
        user = _person(db_session, password=True, google=True)

        response = _set(client, _jwt(user), new_password="new-password-1")

        assert response.status_code == 200
        assert _login(client, "ana@griddo.io", "new-password-1").status_code == 200
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 401

    def test_without_the_current_password_the_session_must_be_fresh(self, client, db_session):
        """A stolen 7-day JWT must not mint a password that outlives it."""
        user = _person(db_session, password=False, google=True)
        stale = _jwt(user, issued_at=datetime.utcnow() - timedelta(minutes=11))

        response = _set(client, stale, new_password="new-password-1")

        assert response.status_code == 403
        # Machine-readable, so the frontend can send people through Google first.
        assert response.json() == {
            "detail": {
                "code": "reauth_required",
                "message": "Sign in with Google again to set a password.",
            }
        }
        db_session.refresh(user)
        assert user.password_hash is None

    def test_the_current_password_works_from_any_session(self, client, db_session):
        user = _person(db_session, password=True, google=True)
        stale = _jwt(user, issued_at=datetime.utcnow() - timedelta(days=1))

        response = _set(client, stale, new_password="new-password-1", current_password=_PASSWORD)

        assert response.status_code == 200
        assert _login(client, "ana@griddo.io", "new-password-1").status_code == 200

    def test_a_wrong_current_password_is_refused(self, client, db_session):
        user = _person(db_session, password=True, google=True)

        response = _set(client, _jwt(user), new_password="new-password-1", current_password="nope")

        assert response.status_code == 400
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200

    def test_without_google_the_current_password_is_required(self, client, db_session):
        """With no Google identity, the password is the only proof of who this is."""
        user = _person(db_session, password=True, google=False)

        response = _set(client, _jwt(user), new_password="new-password-1")

        assert response.status_code == 400
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200

    @pytest.mark.parametrize("current_password", [None, _PASSWORD])
    def test_an_api_key_cannot_set_a_password(self, client, db_session, current_password):
        """Not even with the current password: a leaked key must not become a password."""
        user = _person(db_session, password=True, google=True)
        key = "k" * 43
        user.set_api_key(key)
        db_session.commit()

        response = _set(
            client, key, new_password="new-password-1", current_password=current_password
        )

        assert response.status_code == 403
        assert "API key" in response.json()["detail"]
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200

    def test_it_needs_a_session(self, client):
        response = client.put("/api/v1/auth/password", json={"new_password": "new-password-1"})

        assert response.status_code == 401

    def test_short_passwords_are_refused(self, client, db_session):
        user = _person(db_session, password=False, google=True)

        assert _set(client, _jwt(user), new_password="short").status_code == 422


class TestRemovePassword:
    def test_a_google_account_removes_its_password(self, client, db_session, capsys):
        user = _person(db_session, password=True, google=True)
        capsys.readouterr()

        response = client.delete("/api/v1/auth/password", headers=_bearer(_jwt(user)))

        assert response.status_code == 200
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 401
        assert [e["user_id"] for e in _events(capsys, "auth.password_removed")] == [str(user.id)]

    def test_the_session_must_be_fresh(self, client, db_session):
        """A stolen JWT can't take the owner's password away either."""
        user = _person(db_session, password=True, google=True)
        stale = _jwt(user, issued_at=datetime.utcnow() - timedelta(minutes=11))

        response = client.delete("/api/v1/auth/password", headers=_bearer(stale))

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "reauth_required"
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200

    def test_refused_when_it_is_the_only_way_in(self, client, db_session):
        user = _person(db_session, password=True, google=False)

        response = client.delete("/api/v1/auth/password", headers=_bearer(_jwt(user)))

        assert response.status_code == 409
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200

    def test_an_api_key_cannot_remove_it(self, client, db_session):
        user = _person(db_session, password=True, google=True)
        key = "k" * 43
        user.set_api_key(key)
        db_session.commit()

        response = client.delete("/api/v1/auth/password", headers=_bearer(key))

        assert response.status_code == 403
        assert "API key" in response.json()["detail"]
        assert _login(client, "ana@griddo.io", _PASSWORD).status_code == 200


class TestMe:
    @pytest.mark.parametrize(("password", "google"), [(True, False), (False, True), (True, True)])
    def test_says_how_the_account_signs_in(self, client, db_session, password, google):
        user = _person(db_session, password=password, google=google)

        body = client.get("/api/v1/auth/me", headers=_bearer(_jwt(user))).json()

        assert (body["has_password"], body["has_google"]) == (password, google)


class TestRegister:
    _BODY = {"email": "new@griddo.io", "password": "new-password-1"}

    def test_gone_by_default(self, client, db_session):
        response = client.post("/api/v1/auth/register", json=self._BODY)

        assert response.status_code == 404
        assert db_session.query(User).count() == 0

    def test_not_in_the_api_docs(self, client):
        assert "/api/v1/auth/register" not in client.get("/openapi.json").json()["paths"]

    def test_back_with_the_setting(self, client, allow_password_signup):
        response = client.post("/api/v1/auth/register", json=self._BODY)

        assert response.status_code == 201

    def test_the_app_warns_when_it_is_on(self, allow_password_signup, capsys):
        from main import create_app

        capsys.readouterr()
        create_app()

        (event,) = _events(capsys, "auth.password_signup_enabled")
        assert "never in production" in event["warning"].lower()

    def test_and_says_nothing_when_it_is_off(self, capsys):
        from main import create_app

        capsys.readouterr()
        create_app()

        assert _events(capsys, "auth.password_signup_enabled") == []
