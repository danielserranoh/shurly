"""
Phase 6.3 — rate limits on what anyone can call: the password login (a bcrypt
check each, on the tasks that also serve redirects) and the sign-in endpoints
that write a row per request (Google's and the MCP's). Counted per client IP,
and failed logins per account, in the database so both tasks share the counts.
"""

import json
import re
import time
from itertools import pairwise

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from main import app, create_app
from server.core import get_db
from server.core.auth import create_access_token, hash_password
from server.core.config import settings
from server.core.models import RateLimit, User, UserIdentity
from server.utils import rate_limit
from tests.conftest import TestingSessionLocal

_PASSWORD = "right-password-1"


class _Clock:
    def __init__(self):
        # The start of a 15-minute window (so of a minute's too), plus a second: the
        # windows follow the wall clock, and a test mustn't cross into the next one.
        self.now = time.time() // (15 * 60) * (15 * 60) + 1


@pytest.fixture(autouse=True)
def clock(monkeypatch) -> _Clock:
    frozen = _Clock()
    monkeypatch.setattr(rate_limit, "_now", lambda: frozen.now)
    return frozen


@pytest.fixture
def limits(monkeypatch):
    """Three of everything, so the tests don't have to make hundreds of requests."""
    for name in (
        "rate_limit_login_per_ip",
        "rate_limit_login_failures_per_account",
        "rate_limit_sign_in_per_ip",
        "rate_limit_mcp_clients_per_ip",
    ):
        monkeypatch.setattr(settings, name, 3)


def _from(ip: str) -> TestClient:
    return TestClient(app, client=(ip, 50000))


def _login(client, email="ana@griddo.io", password="wrong-password", **kwargs):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}, **kwargs)


def _events(capsys, name: str) -> list[dict]:
    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


class TestLoginPerIp:
    def test_the_attempt_over_the_limit_is_refused(self, client, limits):
        for i in range(3):
            assert _login(client, email=f"n{i}@griddo.io").status_code == 401

        response = _login(client, email="n9@griddo.io")

        assert response.status_code == 429
        assert 0 < int(response.headers["retry-after"]) <= 60

    def test_another_address_has_its_own_count(self, client, limits):
        for i in range(3):
            _login(client, email=f"n{i}@griddo.io")

        assert _login(_from("203.0.113.7"), email="z@griddo.io").status_code == 401

    def test_the_count_starts_over_in_the_next_window(self, client, limits, clock):
        for i in range(3):
            _login(client, email=f"n{i}@griddo.io")
        clock.now += 60

        assert _login(client, email="z@griddo.io").status_code == 401

    def test_refusals_are_logged_without_the_address(self, client, limits, capsys):
        for i in range(4):
            _login(client, email=f"n{i}@griddo.io")

        (event,) = _events(capsys, "http.rate_limited")
        assert (event["path"], event["limit"]) == ("/api/v1/auth/login", "login_ip")
        assert "testclient" not in json.dumps(event)


class TestLoginPerAccount:
    """Failed attempts only, so the right password isn't counted with an
    attacker's guesses. Anyone can still lock an account's password route for
    the window; signing in with Google stays open."""

    @pytest.fixture
    def ana(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_login_per_ip", 100)
        db_session.add(
            User(email="ana@griddo.io", password_hash=hash_password(_PASSWORD), is_active=True)
        )
        db_session.commit()

    def test_failures_lock_the_password_route_even_for_the_right_password(
        self, client, limits, ana
    ):
        for _ in range(3):
            assert _login(client).status_code == 401

        response = _login(client, password=_PASSWORD)

        assert response.status_code == 429
        assert 60 < int(response.headers["retry-after"]) <= 15 * 60

    def test_successes_do_not_count(self, client, limits, ana):
        for _ in range(5):
            assert _login(client, password=_PASSWORD).status_code == 200

    def test_spread_over_addresses_it_still_counts(self, client, limits, ana):
        """A distributed guess against one account."""
        for i in range(3):
            assert _login(_from(f"203.0.113.{i}")).status_code == 401

        assert _login(_from("203.0.113.99"), password=_PASSWORD).status_code == 429

    def test_an_unknown_address_locks_the_same_way(self, client, limits, ana):
        """Otherwise a 429 would tell which addresses have an account."""
        for _ in range(3):
            assert _login(client, email="nobody@griddo.io").status_code == 401

        assert _login(client, email="nobody@griddo.io").status_code == 429


class TestCurrentPasswordPerAccount:
    """Changing or setting the password with the current one is a guess like a login's. So
    a wrong one counts with the login's failures, by the account's address, and guesses
    spread over every path add up. The same trade-off too: over the limit, the right
    password waits for the window, while signing in with Google stays open."""

    @pytest.fixture
    def ana(self, db_session, monkeypatch) -> User:
        monkeypatch.setattr(settings, "rate_limit_login_per_ip", 100)
        user = User(email="ana@griddo.io", password_hash=hash_password(_PASSWORD), is_active=True)
        db_session.add(user)
        db_session.commit()
        return user

    @staticmethod
    def _signed_in(user: User) -> dict:
        return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}

    def _change(self, client, user, current="wrong-password", new="new-password-1"):
        body = {"current_password": current, "new_password": new}
        return client.post("/api/v1/auth/change-password", json=body, headers=self._signed_in(user))

    def _set(self, client, user, current="wrong-password", new="new-password-1"):
        body = {"current_password": current, "new_password": new}
        return client.put("/api/v1/auth/password", json=body, headers=self._signed_in(user))

    @pytest.mark.parametrize(
        ("guess", "path"),
        [("_change", "/api/v1/auth/change-password"), ("_set", "/api/v1/auth/password")],
    )
    def test_wrong_ones_lock_it_even_for_the_right_password(
        self, client, limits, ana, capsys, guess, path
    ):
        for _ in range(3):
            assert getattr(self, guess)(client, ana).status_code == 400

        response = getattr(self, guess)(client, ana, current=_PASSWORD)

        assert response.status_code == 429
        assert 60 < int(response.headers["retry-after"]) <= 15 * 60
        assert [e["path"] for e in _events(capsys, "http.rate_limited")] == [path]

    def test_guesses_on_every_path_add_up(self, client, limits, ana):
        assert _login(client).status_code == 401
        assert self._change(client, ana).status_code == 400
        assert self._set(client, ana).status_code == 400

        assert _login(client, password=_PASSWORD).status_code == 429
        assert self._change(client, ana, current=_PASSWORD).status_code == 429
        assert self._set(client, ana, current=_PASSWORD).status_code == 429

    def test_the_right_one_does_not_count(self, client, limits, ana):
        """Four changes: one over the limit, had they counted."""
        passwords = [_PASSWORD, "second-pass-1", "third-pass-1", "fourth-pass-1", "fifth-pass-1"]

        for i, (current, new) in enumerate(pairwise(passwords)):
            change = self._set if i % 2 else self._change
            assert change(client, ana, current=current, new=new).status_code == 200

    def test_google_stays_the_way_back(self, client, db_session, limits, ana):
        """Locked, an account that signs in with Google sets a new password without the old one."""
        db_session.add(
            UserIdentity(user_id=ana.id, provider="google", subject="g-ana", email=ana.email)
        )
        db_session.commit()
        for _ in range(3):
            assert _login(client).status_code == 401

        assert self._set(client, ana, current=None).status_code == 200


class TestSignIn:
    def test_google_start_over_the_limit_goes_back_to_the_frontend(
        self, client, limits, monkeypatch
    ):
        """A full-page navigation: the login page shows the error, not raw JSON."""
        monkeypatch.setattr(settings, "frontend_url", "https://app.shurly.test")
        for _ in range(3):
            client.get("/api/v1/auth/google/start", follow_redirects=False)

        response = client.get("/api/v1/auth/google/callback", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "https://app.shurly.test/login/#error=rate_limited"

    def test_without_a_frontend_it_is_a_429(self, client, limits):
        for _ in range(3):
            client.get("/api/v1/auth/google/start", follow_redirects=False)

        assert client.get("/api/v1/auth/google/start").status_code == 429

    def test_the_mcp_sign_in_pages_are_limited(self, client, limits):
        for _ in range(3):
            client.get("/mcp/authorize", follow_redirects=False)

        response = client.get("/mcp/authorize")

        assert response.status_code == 429
        assert response.headers["content-type"].startswith("text/plain")

    def test_mcp_clients_have_their_own_count(self, client, limits):
        """claude.ai calls /mcp/register and /mcp/token from Anthropic's IPs, shared by
        every Griddo person, so they don't eat into the sign-in pages' count."""
        for _ in range(3):
            client.post("/mcp/token")

        assert client.post("/mcp/token").status_code == 429
        assert client.get("/mcp/authorize", follow_redirects=False).status_code != 429


class TestLeftAlone:
    def test_preflights_are_not_counted(self, client, limits):
        for _ in range(10):
            client.options(
                "/api/v1/auth/login",
                headers={
                    "origin": "http://localhost:4232",
                    "access-control-request-method": "POST",
                },
            )

        assert _login(client).status_code == 401

    def test_redirects_and_signed_in_calls_are_not_limited(self, client, limits, auth_headers):
        for _ in range(10):
            assert client.get("/api/v1/auth/me", headers=auth_headers).status_code == 200
            assert client.get("/nosuch", follow_redirects=False).status_code != 429

    def test_zero_turns_a_limit_off(self, client, limits, monkeypatch):
        monkeypatch.setattr(settings, "rate_limit_login_per_ip", 0)
        monkeypatch.setattr(settings, "rate_limit_login_failures_per_account", 0)

        for _ in range(10):
            assert _login(client).status_code == 401


def _session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


class TestSharedAndSafe:
    def test_both_tasks_share_the_count(self, db_session, limits):
        tasks = []
        for _ in range(2):
            task = create_app()
            task.dependency_overrides[get_db] = _session
            tasks.append(TestClient(task))

        for i in range(3):
            assert _login(tasks[i % 2], email=f"n{i}@griddo.io").status_code == 401

        assert _login(tasks[1], email="z@griddo.io").status_code == 429

    def test_a_forged_forwarded_for_does_not_start_a_new_count(self, client, limits, monkeypatch):
        """Behind the ALB: the address the ALB appends counts, not what the client sent."""
        monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
        alb = _from("172.31.0.10")
        for i in range(3):
            forged = {"x-forwarded-for": f"6.6.6.{i}, 203.0.113.9"}
            assert _login(alb, email=f"n{i}@griddo.io", headers=forged).status_code == 401

        forged = {"x-forwarded-for": "6.6.6.200, 203.0.113.9"}
        assert _login(alb, email="z@griddo.io", headers=forged).status_code == 429
        someone_else = {"x-forwarded-for": "203.0.113.10"}
        assert _login(alb, email="y@griddo.io", headers=someone_else).status_code == 401

    def test_no_address_or_email_is_stored(self, client, db_session, limits):
        _login(client)

        keys = [row.key for row in db_session.query(RateLimit).all()]
        assert keys and all(re.fullmatch(r"[0-9a-f]{64}", key) for key in keys)

    def test_if_counting_fails_the_request_goes_through(self, client, limits, monkeypatch, capsys):
        def database_down():
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        monkeypatch.setattr(rate_limit, "session_factory", database_down)

        for i in range(5):
            assert _login(client, email=f"n{i}@griddo.io").status_code == 401

        failures = _events(capsys, "rate_limit.store_failed")
        assert failures and {e["error"] for e in failures} == {"OperationalError"}


class TestBehindCloudFront:
    """Through CloudFront every request reaches the ALB from an edge: the viewer's
    address counts, and only on a request that proves it came through CloudFront."""

    SECRET = "cf-origin-0123456789abcdef0123456789abcdef"

    @pytest.fixture(autouse=True)
    def cloudfront(self, monkeypatch):
        monkeypatch.setattr(settings, "trusted_proxies", ["172.31.0.0/16"])
        monkeypatch.setattr(settings, "cloudfront_origin_secrets", [SecretStr(self.SECRET)])

    def _via_edge(self, ip: str, port: int = 4000, secret: str | None = None) -> dict[str, str]:
        """X-Forwarded-For: the address CloudFront appended, then the edge the ALB did."""
        headers = {
            "x-forwarded-for": f"{ip}, 130.176.0.1",
            "cloudfront-viewer-address": f"{ip}:{port}",
        }
        if secret:
            headers["x-origin-verify"] = secret
        return headers

    def test_people_behind_the_same_edge_have_their_own_count(self, client, limits):
        alb = _from("172.31.0.10")
        for i in range(3):
            headers = self._via_edge("203.0.113.7", secret=self.SECRET)
            assert _login(alb, email=f"n{i}@griddo.io", headers=headers).status_code == 401

        over = self._via_edge("203.0.113.7", port=4001, secret=self.SECRET)
        assert _login(alb, email="z@griddo.io", headers=over).status_code == 429
        colleague = self._via_edge("203.0.113.8", secret=self.SECRET)
        assert _login(alb, email="y@griddo.io", headers=colleague).status_code == 401

    def test_a_forged_viewer_address_does_not_start_a_new_count(self, client, limits):
        """Straight to the shared ALB, without the secret: the edge's address counts."""
        alb = _from("172.31.0.10")
        for i in range(3):
            forged = self._via_edge(f"6.6.6.{i}")
            assert _login(alb, email=f"n{i}@griddo.io", headers=forged).status_code == 401

        forged = self._via_edge("6.6.6.200")
        assert _login(alb, email="z@griddo.io", headers=forged).status_code == 429


def test_the_count_upserts_on_postgresql(pg_engine, monkeypatch, clock):
    """PostgreSQL's INSERT … ON CONFLICT with the CASE, which SQLite's tests don't run."""
    from sqlalchemy.orm import sessionmaker

    from server.core.migrations import run_migrations

    run_migrations(pg_engine)
    monkeypatch.setattr(rate_limit, "session_factory", sessionmaker(bind=pg_engine))
    monkeypatch.setattr(settings, "rate_limit_login_per_ip", 2)

    verdicts = [rate_limit.hit(rate_limit.LOGIN_PER_IP, "203.0.113.1") for _ in range(3)]
    assert [v.allowed for v in verdicts] == [True, True, False]

    clock.now += 60
    assert rate_limit.hit(rate_limit.LOGIN_PER_IP, "203.0.113.1").allowed
    clock.now += 2 * 60 * 60
    rate_limit.hit(rate_limit.LOGIN_PER_IP, "203.0.113.2")
    with pg_engine.connect() as conn:
        from sqlalchemy import text

        assert conn.execute(text("SELECT count(*) FROM rate_limits")).scalar_one() == 1
