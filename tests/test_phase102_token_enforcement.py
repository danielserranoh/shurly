"""
Phase 10.2 — what a service token may do, and from where (server/utils/service_scopes.py,
server/utils/rate_limit.py, `get_service_token` in server/core/auth.py):

- each `/api/v1` route needs a scope, needs none, or is for people only; a new route has to be
  put in one of them (the walk below);
- `X-Shurly-On-Behalf-Of` needs `act_on_behalf`;
- a token with allowed IP ranges works only from inside them;
- a service account's requests are limited per minute, all its tokens together, and every
  response to it says how many are left;
- people's sessions and API keys, and v1's tokens (every scope, any address), work as before.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from main import app
from server.core.config import settings
from server.core.models import OrgRole, ServiceToken
from server.core.models.service_token import SERVICE_SCOPES, every_scope
from server.utils import rate_limit
from server.utils import service_scopes as rules
from tests.test_phase101_service_accounts import (
    ON_BEHALF,
    _api_key,
    _bearer,
    _create_account,
    _issue,
    _person,
    _session,
)

AUTH_DEPENDENCIES = {"get_current_user", "get_signed_in_session", "get_optional_user"}
IGNORED_METHODS = {"HEAD", "OPTIONS"}
RATE_HEADERS = ("ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")
# Values for a route's path parameters: the route is refused before they're looked at.
DUMMY = {
    "short_code": "abc123",
    "rule_id": str(uuid.uuid4()),
    "campaign_id": str(uuid.uuid4()),
    "tag_id": str(uuid.uuid4()),
    "user_id": str(uuid.uuid4()),
    "entry_id": str(uuid.uuid4()),
    "account_id": str(uuid.uuid4()),
}


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


@pytest.fixture
def account(client, team):
    return _create_account(client, team)


@pytest.fixture
def issued(client, team, account):
    """A token as v1 made them: every scope, any address."""
    return _issue(client, team, account["id"])


def _row(db_session, issued) -> ServiceToken:
    return db_session.get(ServiceToken, uuid.UUID(issued["id"]))


def _configure(db_session, issued, *, scopes=None, ranges=None) -> dict:
    """The token's headers, after giving it these scopes and allowed ranges."""
    row = _row(db_session, issued)
    if scopes is not None:
        row.scopes = list(scopes)
    row.allowed_ip_ranges = ranges
    db_session.commit()
    return _bearer(issued["token"])


def _all_but(scope: str) -> list[str]:
    return [s for s in SERVICE_SCOPES if s != scope]


def _from(ip: str) -> TestClient:
    return TestClient(app, client=(ip, 50000))


def _events(capsys, name: str) -> list[dict]:
    lines = capsys.readouterr().err.splitlines()
    return [e for e in (json.loads(x) for x in lines if x.startswith("{")) if e["event"] == name]


def _link(client, headers, **body):
    return client.post(
        "/api/v1/urls", json={"url": "https://propuestas.griddo.io/p/1", **body}, headers=headers
    )


# ---------------------------------------------------------------- Every route has its rule


def _api_routes() -> dict[tuple[str, str], APIRoute]:
    return {
        (method, path): route
        for path, route in rules.api_routes(app.routes)
        if path.startswith("/api/v1")
        for method in route.methods - IGNORED_METHODS
    }


def _dependencies(dependant, found=None) -> set[str]:
    found = set() if found is None else found
    for sub in dependant.dependencies:
        if sub.call is not None:
            found.add(getattr(sub.call, "__name__", ""))
        _dependencies(sub, found)
    return found


def _filled(path: str) -> str:
    return path.format(**DUMMY)


class TestEveryRouteHasItsRule:
    def test_every_api_route_is_put_somewhere_once(self):
        routes = _api_routes()
        assert len(routes) > 60  # the walk reaches into the included routers
        missing, twice = [], []
        for key in routes:
            places = [
                key in rules.SCOPE_FOR,
                key in rules.ANY_TOKEN,
                rules.not_for_services(*key),
                key in rules.PUBLIC,
            ]
            if not any(places):
                missing.append(key)
            elif sum(places) > 1:
                twice.append(key)
        assert not missing, (
            f"Routes with no rule for service tokens: {missing}. Give each a scope "
            "(SCOPE_FOR), or list it in ANY_TOKEN, NOT_FOR_SERVICES or PUBLIC "
            "(server/utils/service_scopes.py)."
        )
        assert not twice, f"Routes in more than one list: {twice}"

    def test_no_rule_names_a_route_that_doesnt_exist(self):
        routes = _api_routes()
        listed = set(rules.SCOPE_FOR) | rules.ANY_TOKEN | rules.NOT_FOR_SERVICES | rules.PUBLIC
        assert not (listed - set(routes))

    def test_public_routes_read_no_token_and_the_others_do(self):
        for key, route in _api_routes().items():
            reads_a_token = bool(_dependencies(route.dependant) & AUTH_DEPENDENCIES)
            assert reads_a_token is (key not in rules.PUBLIC), key

    def test_the_scopes_are_the_models(self):
        assert set(rules.SCOPE_FOR.values()) == set(SERVICE_SCOPES)
        assert (
            rules.URLS_READ,
            rules.URLS_WRITE,
            rules.URLS_DELETE,
            rules.TAGS_WRITE,
            rules.ANALYTICS_READ,
            rules.ACT_ON_BEHALF,
        ) == SERVICE_SCOPES

    def test_the_groups(self):
        def routes_of(scope):
            return {key for key, value in rules.SCOPE_FOR.items() if value == scope}

        assert {method for method, _ in routes_of(rules.URLS_READ)} == {"GET"}
        assert {method for method, _ in routes_of(rules.URLS_DELETE)} == {"DELETE"}
        assert {method for method, _ in routes_of(rules.ANALYTICS_READ)} == {"GET"}
        assert all(path.startswith("/api/v1/analytics/") for _, path in routes_of("analytics:read"))
        assert all(path.startswith("/api/v1/tags") for _, path in routes_of(rules.TAGS_WRITE))
        assert ("GET", "/api/v1/tags") in routes_of(rules.URLS_READ)
        assert ("DELETE", "/api/v1/campaigns/{campaign_id}") in routes_of(rules.URLS_DELETE)
        assert ("POST", "/api/v1/urls/{short_code}/rules") in routes_of(rules.URLS_WRITE)

    def test_every_service_accounts_route_is_for_people(self):
        for method, path in _api_routes():
            if path.startswith("/api/v1/service-accounts"):
                assert rules.not_for_services(method, path)


# ---------------------------------------------------------------- Scopes


class TestScopes:
    def test_each_scoped_route_refuses_a_token_without_its_scope(
        self, client, db_session, issued, monkeypatch
    ):
        monkeypatch.setattr(settings, "service_account_rate_limit_per_minute", 0)
        for (method, path), scope in rules.SCOPE_FOR.items():
            headers = _configure(db_session, issued, scopes=_all_but(scope))
            response = client.request(method, _filled(path), headers=headers)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["code"] == "scope_missing", (method, path)
            assert f"`{scope}`" in response.json()["detail"]

    def test_routes_for_people_refuse_any_token(self, client, db_session, issued, monkeypatch):
        monkeypatch.setattr(settings, "service_account_rate_limit_per_minute", 0)
        headers = _bearer(issued["token"])  # every scope
        for method, path in sorted(rules.NOT_FOR_SERVICES):
            response = client.request(method, _filled(path), headers=headers)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["code"] == "service_account_not_allowed", (method, path)

    def test_a_token_with_no_scope_still_says_who_it_is(self, client, db_session, issued, account):
        headers = _configure(db_session, issued, scopes=[])
        me = client.get("/api/v1/auth/me", headers=headers)
        assert me.status_code == 200
        assert me.json()["id"] == account["id"]
        assert client.get("/api/v1/organization", headers=headers).status_code == 200
        assert client.get("/api/v1/urls", headers=headers).status_code == 403

    def test_urls_read(self, client, db_session, issued):
        _link(client, _bearer(issued["token"]))
        headers = _configure(db_session, issued, scopes=[rules.URLS_READ])
        listed = client.get("/api/v1/urls", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert client.get("/api/v1/tags", headers=headers).status_code == 200
        assert client.get("/api/v1/campaigns", headers=headers).status_code == 200
        refused = _link(client, headers)
        assert refused.status_code == 403
        assert refused.json()["code"] == "scope_missing"
        assert "`urls:write`" in refused.json()["detail"]

    def test_urls_write(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.URLS_WRITE])
        made = _link(client, headers)
        assert made.status_code == 201, made.text
        code = made.json()["short_code"]
        changed = client.patch(f"/api/v1/urls/{code}", json={"title": "T"}, headers=headers)
        assert changed.status_code == 200
        assert client.get(f"/api/v1/urls/{code}", headers=headers).status_code == 403
        assert client.delete(f"/api/v1/urls/{code}", headers=headers).status_code == 403

    def test_urls_delete(self, client, db_session, issued):
        code = _link(client, _bearer(issued["token"])).json()["short_code"]
        headers = _configure(db_session, issued, scopes=[rules.URLS_DELETE])
        assert client.delete(f"/api/v1/urls/{code}", headers=headers).status_code == 204
        assert _link(client, headers).status_code == 403

    def test_tags_write(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.TAGS_WRITE])
        made = client.post("/api/v1/tags", json={"name": "proposals"}, headers=headers)
        assert made.status_code == 201, made.text
        tag_id = made.json()["id"]
        assert client.delete(f"/api/v1/tags/{tag_id}", headers=headers).status_code in (200, 204)
        assert client.get("/api/v1/tags", headers=headers).status_code == 403

    def test_analytics_read(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.ANALYTICS_READ])
        assert client.get("/api/v1/analytics/overview", headers=headers).status_code == 200
        assert client.get("/api/v1/urls", headers=headers).status_code == 403
        refused = _configure(db_session, issued, scopes=_all_but(rules.ANALYTICS_READ))
        response = client.get("/api/v1/analytics/overview", headers=refused)
        assert response.status_code == 403
        assert "`analytics:read`" in response.json()["detail"]

    def test_the_people_list_needs_act_on_behalf(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.ACT_ON_BEHALF])
        members = client.get("/api/v1/organization/members", headers=headers)
        assert members.status_code == 200
        assert "ana.garcia@griddo.io" in {m["email"] for m in members.json()}
        headers = _configure(db_session, issued, scopes=_all_but(rules.ACT_ON_BEHALF))
        assert client.get("/api/v1/organization/members", headers=headers).status_code == 403

    def test_a_refusal_is_logged_with_ids_only(self, client, db_session, issued, capsys):
        headers = _configure(db_session, issued, scopes=[])
        capsys.readouterr()
        client.get("/api/v1/urls?search=secret-thing", headers=headers)
        [event] = _events(capsys, "service_token.refused")
        assert event["reason"] == "scope"
        assert event["scope"] == "urls:read"
        assert event["route"] == "/api/v1/urls"
        assert event["token_id"] == issued["id"]
        assert "secret-thing" not in json.dumps(event)


# ---------------------------------------------------------------- Acting on behalf


class TestActOnBehalf:
    def test_naming_a_person_needs_the_scope(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.URLS_WRITE])
        refused = _link(client, {**headers, ON_BEHALF: "ana.garcia@griddo.io"})
        assert refused.status_code == 403
        assert refused.json()["code"] == "scope_missing"
        assert "`act_on_behalf`" in refused.json()["detail"]
        assert (
            client.get("/api/v1/urls", headers=_session_of_owner(db_session)).json()["total"] == 0
        )

    def test_without_the_header_it_acts_for_itself(self, client, db_session, issued, account):
        headers = _configure(db_session, issued, scopes=[rules.URLS_WRITE])
        made = _link(client, headers)
        assert made.status_code == 201
        assert made.json()["via_service_account"]["id"] == account["id"]
        blank = _link(client, {**headers, ON_BEHALF: "  "})  # names nobody
        assert blank.status_code == 201

    def test_with_the_scope_the_person_is_the_creator(self, client, db_session, issued):
        headers = _configure(db_session, issued, scopes=[rules.URLS_WRITE, rules.ACT_ON_BEHALF])
        made = _link(client, {**headers, ON_BEHALF: "ana.garcia@griddo.io"})
        assert made.status_code == 201, made.text
        assert made.json()["created_by_email"] == "ana.garcia@griddo.io"

    def test_on_a_change_too(self, client, db_session, issued):
        code = _link(client, _bearer(issued["token"])).json()["short_code"]
        headers = _configure(db_session, issued, scopes=[rules.URLS_WRITE])
        response = client.patch(
            f"/api/v1/urls/{code}",
            json={"title": "T"},
            headers={**headers, ON_BEHALF: "ana.garcia@griddo.io"},
        )
        assert response.status_code == 403
        assert "`act_on_behalf`" in response.json()["detail"]


def _session_of_owner(db_session) -> dict:
    from server.core.models import User

    return _session(db_session.query(User).filter_by(email="owner@griddo.io").one())


# ---------------------------------------------------------------- Allowed IP ranges


class TestAllowedRanges:
    @pytest.mark.parametrize(
        ("ranges", "inside", "outside"),
        [
            (["203.0.113.0/24"], "203.0.113.7", "198.51.100.7"),
            (["198.51.100.7/32", "203.0.113.0/24"], "198.51.100.7", "198.51.100.8"),
            (["2001:db8::/32"], "2001:db8::1", "2001:db9::1"),
            (["2001:db8::/32", "203.0.113.0/24"], "203.0.113.200", "2001:db9::1"),
        ],
    )
    def test_in_and_out(self, client, db_session, issued, capsys, ranges, inside, outside):
        headers = _configure(db_session, issued, ranges=ranges)
        assert _from(inside).get("/api/v1/auth/me", headers=headers).status_code == 200

        capsys.readouterr()
        refused = _from(outside).get("/api/v1/auth/me", headers=headers)
        assert refused.status_code == 403
        assert refused.json()["code"] == "ip_not_allowed"
        assert outside not in refused.text
        logged = capsys.readouterr().err
        assert outside not in logged
        assert '"reason": "address"' in logged

    @pytest.mark.parametrize("ranges", [None, []])
    def test_none_or_empty_is_any_address(self, client, db_session, issued, ranges):
        headers = _configure(db_session, issued, ranges=ranges)
        for ip in ("203.0.113.7", "2001:db8::1", "198.51.100.1"):
            assert _from(ip).get("/api/v1/auth/me", headers=headers).status_code == 200

    def test_behind_a_trusted_proxy_the_client_is_checked(
        self, client, db_session, issued, monkeypatch
    ):
        monkeypatch.setattr(settings, "trusted_proxies", ["10.0.0.0/8"])
        headers = _configure(db_session, issued, ranges=["203.0.113.0/24"])
        alb = _from("10.0.0.5")
        inside = alb.get("/api/v1/auth/me", headers={**headers, "X-Forwarded-For": "203.0.113.7"})
        assert inside.status_code == 200
        outside = alb.get("/api/v1/auth/me", headers={**headers, "X-Forwarded-For": "198.51.100.7"})
        assert outside.status_code == 403
        # The proxy's own address isn't the client's.
        assert alb.get("/api/v1/auth/me", headers=headers).status_code == 403

    def test_a_refused_address_is_neither_a_use_nor_counted(self, client, db_session, issued):
        headers = _configure(db_session, issued, ranges=["203.0.113.0/24"])
        refused = _from("198.51.100.7").get("/api/v1/auth/me", headers=headers)
        assert refused.status_code == 403
        assert not any(name in refused.headers for name in RATE_HEADERS)
        db_session.expire_all()
        assert _row(db_session, issued).last_used_at is None

    def test_the_rule(self):
        assert rules.address_allowed("203.0.113.7", None)
        assert rules.address_allowed("anything", [])
        assert rules.address_allowed("203.0.113.7", ["203.0.113.0/24"])
        assert not rules.address_allowed("203.0.113.7", ["2001:db8::/32"])
        assert rules.address_allowed("::ffff:203.0.113.7", ["203.0.113.0/24"])
        assert rules.address_allowed("2001:db8::abcd", ["2001:db8::/32"])
        assert not rules.address_allowed("testclient", ["203.0.113.0/24"])
        assert not rules.address_allowed("203.0.113.7", ["not a range"])
        assert rules.address_allowed("203.0.113.7", ["not a range", "203.0.113.7"])


# ---------------------------------------------------------------- Rate limit


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        # A second into a minute: a test mustn't cross into the next window by accident.
        now = time.time() // 60 * 60 + 1

    monkeypatch.setattr(rate_limit, "_now", lambda: Clock.now)
    return Clock


@pytest.fixture
def three_a_minute(monkeypatch):
    monkeypatch.setattr(settings, "service_account_rate_limit_per_minute", 3)


class TestRateLimit:
    def test_every_response_says_where_it_stands(self, client, issued, clock, three_a_minute):
        headers = _bearer(issued["token"])
        remaining = []
        for _ in range(3):
            response = client.get("/api/v1/auth/me", headers=headers)
            assert response.status_code == 200
            assert response.headers["ratelimit-limit"] == "3"
            assert response.headers["ratelimit-reset"] == "59"
            remaining.append(response.headers["ratelimit-remaining"])
        assert remaining == ["2", "1", "0"]

        refused = client.get("/api/v1/auth/me", headers=headers)
        assert refused.status_code == 429
        assert refused.headers["retry-after"] == "59"
        assert refused.headers["ratelimit-limit"] == "3"
        assert refused.headers["ratelimit-remaining"] == "0"
        assert refused.headers["ratelimit-reset"] == "59"
        assert "Try again in 59 seconds" in refused.json()["detail"]

    def test_the_next_window_starts_over(self, client, issued, clock, three_a_minute):
        headers = _bearer(issued["token"])
        for _ in range(4):
            client.get("/api/v1/auth/me", headers=headers)
        clock.now += 30
        assert client.get("/api/v1/auth/me", headers=headers).headers["retry-after"] == "29"
        clock.now += 30
        again = client.get("/api/v1/auth/me", headers=headers)
        assert again.status_code == 200
        assert again.headers["ratelimit-remaining"] == "2"

    def test_both_live_tokens_of_an_account_share_it(
        self, client, team, account, issued, clock, three_a_minute
    ):
        old = _bearer(issued["token"])
        new = _bearer(_issue(client, team, account["id"])["token"])
        assert client.get("/api/v1/auth/me", headers=old).status_code == 200
        assert client.get("/api/v1/auth/me", headers=old).status_code == 200
        last = client.get("/api/v1/auth/me", headers=new)
        assert last.status_code == 200
        assert last.headers["ratelimit-remaining"] == "0"
        assert client.get("/api/v1/auth/me", headers=new).status_code == 429
        assert client.get("/api/v1/auth/me", headers=old).status_code == 429

    def test_another_account_has_its_own(self, client, team, issued, clock, three_a_minute):
        other = _create_account(client, team, name="Another")
        theirs = _bearer(_issue(client, team, other["id"])["token"])
        for _ in range(4):
            client.get("/api/v1/auth/me", headers=_bearer(issued["token"]))
        assert client.get("/api/v1/auth/me", headers=theirs).status_code == 200

    def test_refusals_count_and_carry_the_headers(
        self, client, db_session, issued, clock, three_a_minute
    ):
        headers = _configure(db_session, issued, scopes=[])
        refused = client.get("/api/v1/urls", headers=headers)
        assert refused.status_code == 403
        assert refused.headers["ratelimit-remaining"] == "2"
        not_for_it = client.get("/api/v1/service-accounts", headers=headers)
        assert not_for_it.status_code == 403
        assert not_for_it.headers["ratelimit-remaining"] == "1"

    def test_errors_from_the_route_carry_them_too(self, client, issued, clock, three_a_minute):
        missing = client.get("/api/v1/urls/nope00", headers=_bearer(issued["token"]))
        assert missing.status_code == 404
        assert missing.headers["ratelimit-remaining"] == "2"

    def test_the_browser_may_read_them(self, client, issued):
        response = client.get(
            "/api/v1/auth/me",
            headers={**_bearer(issued["token"]), "Origin": "http://localhost:4232"},
        )
        exposed = response.headers["access-control-expose-headers"].lower()
        assert all(name in exposed for name in RATE_HEADERS)
        assert "retry-after" in exposed

    def test_people_are_not_limited(self, client, db_session, team, clock, three_a_minute):
        key = _api_key(db_session, team["bob"])
        session = _session(team["ana"])
        for _ in range(5):
            for headers in (key, session):
                response = client.get("/api/v1/urls", headers=headers)
                assert response.status_code == 200
                assert not any(name in response.headers for name in RATE_HEADERS)

    def test_zero_turns_it_off(self, client, issued, monkeypatch):
        monkeypatch.setattr(settings, "service_account_rate_limit_per_minute", 0)
        for _ in range(5):
            response = client.get("/api/v1/auth/me", headers=_bearer(issued["token"]))
            assert response.status_code == 200
            assert not any(name in response.headers for name in RATE_HEADERS)

    def test_if_the_database_cant_count_the_request_goes_through(
        self, client, issued, monkeypatch, capsys
    ):
        def broken(*_args):
            raise OperationalError("UPDATE rate_limits", {}, Exception("down"))

        monkeypatch.setattr(rate_limit, "_increment", broken)
        capsys.readouterr()
        response = client.get("/api/v1/auth/me", headers=_bearer(issued["token"]))
        assert response.status_code == 200
        assert not any(name in response.headers for name in RATE_HEADERS)
        [event] = _events(capsys, "rate_limit.store_failed")
        assert event["limit"] == "service_account"

    def test_the_count_is_kept_by_account_never_by_token(self, client, issued, db_session):
        from server.core.models import RateLimit

        client.get("/api/v1/auth/me", headers=_bearer(issued["token"]))
        keys = [row.key for row in db_session.query(RateLimit).all()]
        assert keys == [rate_limit._key(rate_limit.SERVICE_ACCOUNT, issued_account(db_session))]
        assert issued["token"] not in json.dumps(keys)


def issued_account(db_session) -> str:
    [row] = db_session.query(ServiceToken).all()
    return str(row.service_account_id)


# ---------------------------------------------------------------- As before


class TestAsBefore:
    def test_a_v1_token_has_every_scope_and_any_address(self, issued, db_session):
        row = _row(db_session, issued)
        assert row.scopes == every_scope()
        assert row.allowed_ip_ranges is None

    def test_a_v1_token_does_what_it_did(self, client, team, issued, account):
        headers = _bearer(issued["token"])
        for_ana = {**headers, ON_BEHALF: "ana.garcia@griddo.io"}
        assert client.get("/api/v1/auth/me", headers=headers).json()["id"] == account["id"]
        assert client.get("/api/v1/organization", headers=headers).status_code == 200
        assert client.get("/api/v1/organization/members", headers=headers).status_code == 200

        made = _link(client, for_ana)
        assert made.status_code == 201, made.text
        assert made.json()["created_by_email"] == "ana.garcia@griddo.io"
        code = made.json()["short_code"]
        assert client.get(f"/api/v1/urls/{code}", headers=headers).status_code == 200
        changed = client.patch(f"/api/v1/urls/{code}", json={"valid_until": None}, headers=for_ana)
        assert changed.status_code == 200, changed.text
        assert client.get("/api/v1/tags", headers=headers).status_code == 200
        assert client.get("/api/v1/analytics/overview", headers=headers).status_code == 200
        assert (
            client.get(f"/api/v1/analytics/urls/{code}/totals", headers=headers).status_code == 200
        )
        assert client.delete(f"/api/v1/urls/{code}", headers=for_ana).status_code == 204
        # Its rate limit is the only new thing it sees.
        assert client.get("/api/v1/auth/me", headers=headers).headers["ratelimit-limit"] == "120"

    def test_people_are_unaffected(self, client, db_session, team):
        key = _api_key(db_session, team["bob"])
        assert client.get("/api/v1/auth/me", headers=key).json()["email"] == "bob@griddo.io"
        assert _link(client, key).status_code == 201
        assert _link(client, _session(team["ana"])).status_code == 201
        assert client.get("/api/v1/organization/members", headers=key).status_code == 200
        # The header from a person is still v1's 403.
        refused = _link(client, {**key, ON_BEHALF: "ana.garcia@griddo.io"})
        assert refused.status_code == 403
        assert refused.json()["code"] == "on_behalf_of_not_allowed"
        # And their own routes, which no service token reaches, still answer them.
        assert (
            client.get("/api/v1/service-accounts", headers=_session(team["owner"])).status_code
            == 200
        )

    def test_an_unknown_token_is_still_the_same_401(self, client):
        response = client.get("/api/v1/auth/me", headers=_bearer("shsa_00000000_nope"))
        assert response.status_code == 401
        assert not any(name in response.headers for name in RATE_HEADERS)
