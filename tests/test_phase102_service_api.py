"""
Phase 10.2 — the service accounts' API, v2 (`_pm/spec_service_accounts.md`; plan T5).

- **Token settings.** Making or renewing a token takes optional `scopes` (at least one, each
  known, deduplicated) and `allowed_ip_ranges` (CIDRs, stored as their network; empty or null:
  any address). Left out, a first token gets every scope and any address, as in v1, and a
  renewal keeps those of the token it replaces.
- **Warnings.** The active token says `expires_soon` (it stops working within 14 days) and
  `unused` (nothing has used it for 90 days); `attention_count` counts the tokens with one.
- **Audit rows** for the events on an account and its tokens, the owner as their actor, in the
  change's transaction.
- **`GET /api/v1/service-accounts/audit`**: owners and admins, their organization's rows only,
  newest first, paged by `before`, people and links looked up when read.
- **v1's requests** answer as they did.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from main import app
from server.core.models import (
    URL,
    AuditEvent,
    Organization,
    OrganizationMember,
    OrgRole,
    ServiceToken,
    User,
)
from server.core.models.service_token import SERVICE_SCOPES
from server.utils import audit
from server.utils import service_accounts as service
from server.utils.service_accounts import Acting
from server.utils.service_scopes import not_for_services
from tests.test_phase101_service_accounts import (
    BASE,
    ON_BEHALF,
    _api_key,
    _bearer,
    _create_account,
    _for_ana,
    _issue,
    _make_link,
    _person,
    _session,
)

AUDIT = f"{BASE}/audit"
V1_TOKEN_FIELDS = {"id", "prefix", "created_at", "expires_at", "last_used_at", "valid_until"}


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


@pytest.fixture
def account(client, team) -> dict:
    return _create_account(client, team)


def _post_token(client, team, account_id: str, body):
    return client.post(f"{BASE}/{account_id}/token", json=body, headers=_session(team["owner"]))


def _row(db_session, token_id: str) -> ServiceToken:
    db_session.expire_all()
    return db_session.get(ServiceToken, uuid.UUID(token_id))


def _audit_rows(db_session) -> list[AuditEvent]:
    db_session.expire_all()
    return db_session.query(AuditEvent).order_by(AuditEvent.at, AuditEvent.action).all()


def _clear_audit(db_session) -> None:
    db_session.query(AuditEvent).delete()
    db_session.commit()


def _listed(client, team) -> dict:
    response = client.get(BASE, headers=_session(team["owner"]))
    assert response.status_code == 200, response.text
    return response.json()[0]


def _organization_id(db_session, user: User) -> uuid.UUID:
    return (
        db_session.query(OrganizationMember)
        .filter(OrganizationMember.user_id == user.id)
        .one()
        .organization_id
    )


# ---------------------------------------------------------------- Token settings


class TestTokenSettings:
    def test_a_first_token_without_them_gets_every_scope_and_any_address(
        self, client, team, account, db_session
    ):
        issued = _issue(client, team, account["id"])
        assert issued["scopes"] == list(SERVICE_SCOPES)
        assert issued["allowed_ip_ranges"] == []
        assert issued["warnings"] == []
        row = _row(db_session, issued["id"])
        assert row.scopes == list(SERVICE_SCOPES)
        assert row.allowed_ip_ranges is None

    def test_scopes_and_ranges_are_kept_cleaned(self, client, team, account, db_session):
        response = _post_token(
            client,
            team,
            account["id"],
            {
                "scopes": ["urls:write", "urls:read", "urls:read"],
                "allowed_ip_ranges": [
                    " 203.0.113.77/24",
                    "2001:db8::1/32",
                    "203.0.113.0/24",
                    "198.51.100.7",
                ],
            },
        )
        assert response.status_code == 201, response.text
        issued = response.json()
        assert issued["scopes"] == ["urls:read", "urls:write"]  # once each, in the model's order
        ranges = ["203.0.113.0/24", "2001:db8::/32", "198.51.100.7/32"]
        assert issued["allowed_ip_ranges"] == ranges
        row = _row(db_session, issued["id"])
        assert (row.scopes, row.allowed_ip_ranges) == (["urls:read", "urls:write"], ranges)
        listed = _listed(client, team)["token"]
        assert (listed["scopes"], listed["allowed_ip_ranges"]) == (
            ["urls:read", "urls:write"],
            ranges,
        )

    def test_an_empty_or_null_range_list_is_any_address(self, client, team, account, db_session):
        for ranges in ([], None):
            response = _post_token(client, team, account["id"], {"allowed_ip_ranges": ranges})
            assert response.status_code == 201, response.text
            assert response.json()["allowed_ip_ranges"] == []
            assert _row(db_session, response.json()["id"]).allowed_ip_ranges is None

    def test_the_token_is_held_to_them(self, client, team, account):
        issued = _post_token(client, team, account["id"], {"scopes": ["urls:read"]}).json()
        headers = _bearer(issued["token"])
        assert client.get("/api/v1/urls", headers=headers).status_code == 200
        refused = _make_link(client, headers)
        assert refused.status_code == 403
        assert refused.json()["code"] == "scope_missing"

        ranged = _post_token(
            client, team, account["id"], {"allowed_ip_ranges": ["203.0.113.0/24"]}
        ).json()
        headers = _bearer(ranged["token"])
        assert (
            TestClient(app, client=("203.0.113.9", 50000))
            .get("/api/v1/urls", headers=headers)
            .status_code
            == 200
        )
        outside = TestClient(app, client=("198.51.100.9", 50000)).get(
            "/api/v1/urls", headers=headers
        )
        assert outside.status_code == 403
        assert outside.json()["code"] == "ip_not_allowed"


class TestRenewal:
    def _first(self, client, team, account) -> dict:
        response = _post_token(
            client,
            team,
            account["id"],
            {"scopes": ["urls:read", "act_on_behalf"], "allowed_ip_ranges": ["10.0.0.0/8"]},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_it_inherits_both(self, client, team, account, db_session):
        first = self._first(client, team, account)
        renewed = _issue(client, team, account["id"])
        assert renewed["renewed"] is True
        assert renewed["scopes"] == ["urls:read", "act_on_behalf"]
        assert renewed["allowed_ip_ranges"] == ["10.0.0.0/8"]
        row = _row(db_session, renewed["id"])
        assert (row.scopes, row.allowed_ip_ranges) == (
            ["urls:read", "act_on_behalf"],
            ["10.0.0.0/8"],
        )
        # The replaced token keeps its own, and is shown with them in its overlap.
        previous = _listed(client, team)["previous_token"]
        assert previous["id"] == first["id"]
        assert previous["scopes"] == ["urls:read", "act_on_behalf"]

    def test_with_an_expiry_only_it_still_inherits(self, client, team, account):
        self._first(client, team, account)
        expires = (datetime.utcnow() + timedelta(days=365)).isoformat() + "Z"
        renewed = _issue(client, team, account["id"], expires_at=expires)
        assert renewed["scopes"] == ["urls:read", "act_on_behalf"]
        assert renewed["allowed_ip_ranges"] == ["10.0.0.0/8"]

    def test_what_the_request_sets_replaces_what_it_would_inherit(self, client, team, account):
        self._first(client, team, account)
        renewed = _post_token(client, team, account["id"], {"scopes": ["tags:write"]}).json()
        assert renewed["scopes"] == ["tags:write"]
        assert renewed["allowed_ip_ranges"] == ["10.0.0.0/8"]  # not sent: inherited

        cleared = _post_token(client, team, account["id"], {"allowed_ip_ranges": None}).json()
        assert cleared["scopes"] == ["tags:write"]
        assert cleared["allowed_ip_ranges"] == []

        explicit_null_scopes = _post_token(client, team, account["id"], {"scopes": None}).json()
        assert explicit_null_scopes["scopes"] == ["tags:write"]  # null scopes: inherited

    def test_after_a_revoke_a_new_token_starts_from_every_scope(self, client, team, account):
        self._first(client, team, account)
        revoked = client.delete(f"{BASE}/{account['id']}/token", headers=_session(team["owner"]))
        assert revoked.status_code == 204
        fresh = _issue(client, team, account["id"])
        assert fresh["renewed"] is False
        assert fresh["scopes"] == list(SERVICE_SCOPES)
        assert fresh["allowed_ip_ranges"] == []


class TestInvalidSettings:
    @pytest.mark.parametrize(
        "body",
        [
            {"scopes": ["urls:admin"]},
            {"scopes": ["urls:read", "everything"]},
            {"scopes": []},
            {"allowed_ip_ranges": ["10.0.0.0/33"]},
            {"allowed_ip_ranges": ["not-an-ip"]},
            {"allowed_ip_ranges": ["203.0.113.0/24", ""]},
            {"allowed_ip_ranges": ["10.0.0.0/8"] * 51},
            {"scope": ["urls:read"]},  # a typo: extra fields are still refused
        ],
    )
    def test_a_422_and_no_token(self, client, team, account, db_session, body):
        response = _post_token(client, team, account["id"], body)
        assert response.status_code == 422, response.text
        assert db_session.query(ServiceToken).count() == 0
        assert not [row for row in _audit_rows(db_session) if row.target_type == "service_token"]

    def test_the_rules_hold_without_the_schema(self, db_session, team, account):
        for scopes in ([], ["urls:admin"]):
            with pytest.raises(service.Invalid):
                service.issue_token(
                    db_session, team["owner"], uuid.UUID(account["id"]), None, scopes=scopes
                )
        db_session.rollback()


class TestV1Requests:
    """Old clients send only `expires_at`, or nothing: the same answer, plus the new fields."""

    @pytest.mark.parametrize("body", [None, {}, {"expires_at": None}])
    def test_no_settings(self, client, team, account, body):
        response = _post_token(client, team, account["id"], body)
        assert response.status_code == 201, response.text
        issued = response.json()
        assert V1_TOKEN_FIELDS <= set(issued)
        assert issued["expires_at"] is None and issued["renewed"] is False
        assert issued["token"].startswith(f"{issued['prefix']}_")
        assert issued["scopes"] == list(SERVICE_SCOPES) and issued["allowed_ip_ranges"] == []

    def test_an_expiry(self, client, team, account):
        expires = (datetime.utcnow() + timedelta(days=30)).replace(microsecond=0)
        issued = _issue(client, team, account["id"], expires_at=expires.isoformat() + "Z")
        assert issued["expires_at"] == expires.isoformat() + "Z"
        assert issued["warnings"] == []

    def test_an_expiry_in_the_past_is_still_a_422(self, client, team, account):
        past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
        response = _post_token(client, team, account["id"], {"expires_at": past})
        assert response.status_code == 422

    def test_the_list_keeps_its_shape(self, client, team, account):
        _issue(client, team, account["id"])
        listed = _listed(client, team)
        assert V1_TOKEN_FIELDS <= set(listed["token"])
        assert listed["previous_token"] is None


# ---------------------------------------------------------------- Warnings

NOW = datetime(2026, 10, 19, 12, 0, 0)


def _token(**fields) -> ServiceToken:
    values = {"created_at": NOW - timedelta(days=1), "last_used_at": None, "expires_at": None}
    values.update(fields)
    return ServiceToken(
        service_account_id=uuid.uuid4(), prefix="abcd1234", token_hash="x", **values
    )


class TestWarnings:
    @pytest.mark.parametrize(
        ("fields", "expected"),
        [
            ({}, []),
            ({"expires_at": NOW + timedelta(days=14)}, ["expires_soon"]),
            ({"expires_at": NOW + timedelta(days=14, microseconds=1)}, []),
            ({"expires_at": NOW + timedelta(seconds=1)}, ["expires_soon"]),
            ({"expires_at": NOW}, []),  # expired: it no longer works, nothing to warn about
            ({"last_used_at": NOW - timedelta(days=90)}, ["unused"]),
            ({"last_used_at": NOW - timedelta(days=90) + timedelta(microseconds=1)}, []),
            ({"created_at": NOW - timedelta(days=90)}, ["unused"]),  # never used
            ({"created_at": NOW - timedelta(days=89)}, []),
            (
                {"created_at": NOW - timedelta(days=200), "last_used_at": NOW - timedelta(days=1)},
                [],
            ),
            (
                {"created_at": NOW - timedelta(days=100), "expires_at": NOW + timedelta(days=3)},
                ["expires_soon", "unused"],
            ),
            # In its overlap after a renewal, or revoked: no warning.
            (
                {"created_at": NOW - timedelta(days=100), "replaced_at": NOW - timedelta(hours=1)},
                [],
            ),
            ({"created_at": NOW - timedelta(days=100), "revoked_at": NOW}, []),
        ],
    )
    def test_the_boundaries(self, fields, expected):
        assert service.token_warnings(_token(**fields), NOW) == expected

    def test_shown_on_the_active_token(self, client, team, account, db_session):
        issued = _issue(client, team, account["id"])
        row = _row(db_session, issued["id"])
        row.expires_at = datetime.utcnow() + timedelta(days=13)
        row.created_at = datetime.utcnow() - timedelta(days=91)
        db_session.commit()
        assert _listed(client, team)["token"]["warnings"] == ["expires_soon", "unused"]

        row.last_used_at = datetime.utcnow() - timedelta(days=1)
        row.expires_at = datetime.utcnow() + timedelta(days=15)
        db_session.commit()
        assert _listed(client, team)["token"]["warnings"] == []

    def test_attention_counts_the_live_tokens_with_one(self, client, team, db_session):
        old = datetime.utcnow() - timedelta(days=120)
        quiet = _create_account(client, team, name="Quiet")
        busy = _create_account(client, team, name="Busy")
        gone = _create_account(client, team, name="Gone")
        for made in (quiet, busy, gone):
            _issue(client, team, made["id"])
        db_session.query(ServiceToken).update({ServiceToken.created_at: old})
        db_session.commit()
        busy_token = (
            db_session.query(ServiceToken)
            .filter(ServiceToken.service_account_id == uuid.UUID(busy["id"]))
            .one()
        )
        busy_token.last_used_at = datetime.utcnow()
        db_session.commit()
        removed = client.delete(f"{BASE}/{gone['id']}", headers=_session(team["owner"]))
        assert removed.status_code == 204

        organization_id = _organization_id(db_session, team["owner"])
        assert service.attention_count(db_session, organization_id) == 1  # Quiet's
        # A renewal: the new token is fresh, and the old one in its overlap doesn't count.
        _issue(client, team, quiet["id"])
        assert service.attention_count(db_session, organization_id) == 0
        assert service.attention_count(db_session, uuid.uuid4()) == 0


# ---------------------------------------------------------------- Audit rows for account events


class TestAccountEvents:
    def _only(self, db_session, action: str) -> AuditEvent:
        rows = [row for row in _audit_rows(db_session) if row.action == action]
        assert len(rows) == 1, [row.action for row in _audit_rows(db_session)]
        return rows[0]

    def _by_owner(self, row, db_session, team, account) -> None:
        assert row.actor_id == team["owner"].id
        assert str(row.service_account_id) == account["id"]
        assert row.organization_id == _organization_id(db_session, team["owner"])
        assert row.on_behalf_of_id is None

    def test_created(self, client, team, account, db_session):
        row = self._only(db_session, "service_account.created")
        self._by_owner(row, db_session, team, account)
        assert (row.target_type, row.target_id, row.token_id) == (
            "service_account",
            account["id"],
            None,
        )
        assert row.detail is None

    def test_updated_names_the_fields_only(self, client, team, account, db_session):
        _clear_audit(db_session)
        response = client.patch(
            f"{BASE}/{account['id']}",
            json={"display_name": "Propuestas (secret name)", "role": "admin"},
            headers=_session(team["owner"]),
        )
        assert response.status_code == 200, response.text
        row = self._only(db_session, "service_account.updated")
        self._by_owner(row, db_session, team, account)
        assert row.detail == {"fields": ["display_name", "role"]}
        assert "secret name" not in str(row.detail)

    def test_an_update_that_changes_nothing_writes_nothing(self, client, team, account, db_session):
        _clear_audit(db_session)
        response = client.patch(
            f"{BASE}/{account['id']}", json={"role": "member"}, headers=_session(team["owner"])
        )
        assert response.status_code == 200
        assert _audit_rows(db_session) == []

    def test_token_created_renewed_revoked(self, client, team, account, db_session):
        first = _issue(client, team, account["id"])
        row = self._only(db_session, "service_token.created")
        self._by_owner(row, db_session, team, account)
        assert (row.target_type, row.target_id, str(row.token_id)) == (
            "service_token",
            first["id"],
            first["id"],
        )

        second = _issue(client, team, account["id"])
        row = self._only(db_session, "service_token.renewed")
        self._by_owner(row, db_session, team, account)
        assert (row.target_id, str(row.token_id)) == (second["id"], second["id"])
        assert row.detail == {"replaced_token_id": first["id"]}

        _clear_audit(db_session)
        old = client.delete(
            f"{BASE}/{account['id']}/token?old_only=true", headers=_session(team["owner"])
        )
        assert old.status_code == 204
        row = self._only(db_session, "service_token.revoked")
        self._by_owner(row, db_session, team, account)
        assert str(row.token_id) == first["id"]

        _clear_audit(db_session)
        client.delete(f"{BASE}/{account['id']}/token", headers=_session(team["owner"]))
        assert str(self._only(db_session, "service_token.revoked").token_id) == second["id"]

    def test_removed_revokes_each_token_and_removes(self, client, team, account, db_session):
        first = _issue(client, team, account["id"])
        second = _issue(client, team, account["id"])
        _clear_audit(db_session)
        removed = client.delete(f"{BASE}/{account['id']}", headers=_session(team["owner"]))
        assert removed.status_code == 204
        rows = _audit_rows(db_session)
        revoked = {str(row.token_id) for row in rows if row.action == "service_token.revoked"}
        assert revoked == {first["id"], second["id"]}
        row = self._only(db_session, "service_account.removed")
        self._by_owner(row, db_session, team, account)
        # Its organization is kept although the membership is gone.
        assert all(r.organization_id == row.organization_id for r in rows)

    def test_a_refused_change_writes_nothing(self, client, team, account, db_session):
        _clear_audit(db_session)
        for user in (team["admin"], team["ana"]):
            response = client.post(f"{BASE}/{account['id']}/token", headers=_session(user))
            assert response.status_code == 403
        assert _audit_rows(db_session) == []

    def test_the_row_is_in_the_callers_transaction(self, db_session, team):
        _clear_audit(db_session)
        service.create_account(
            db_session,
            team["owner"],
            display_name="Rolled back",
            description=None,
            responsible_user_id=team["ana"].id,
            role="member",
        )
        # Added to the session, neither flushed nor committed: the caller decides.
        assert [type(added) for added in db_session.new] == [AuditEvent]
        db_session.rollback()
        assert _audit_rows(db_session) == []


# ---------------------------------------------------------------- The audit route


@pytest.fixture
def propuestas(client, team, account) -> dict:
    issued = _issue(client, team, account["id"])
    return {"account": account, "token": issued["token"], "issued": issued}


def _read(client, user, **params):
    return client.get(AUDIT, params=params, headers=_session(user))


def _other_organization(client, db_session) -> dict:
    """Another organization, its owner, and a service account there that made a link."""
    other = Organization(name="Other")
    db_session.add(other)
    db_session.flush()
    owner = _person(db_session, "owner@other.example", None)
    db_session.add(
        OrganizationMember(organization_id=other.id, user_id=owner.id, role=OrgRole.OWNER)
    )
    db_session.commit()
    made = client.post(
        BASE,
        json={"display_name": "Elsewhere", "responsible_user_id": str(owner.id)},
        headers=_session(owner),
    )
    assert made.status_code == 201, made.text
    token = client.post(f"{BASE}/{made.json()['id']}/token", headers=_session(owner)).json()
    assert _make_link(client, _bearer(token["token"])).status_code == 201
    return {"owner": owner, "account": made.json()}


class TestAuditRoute:
    def test_owners_and_admins_read_it(self, client, team, propuestas):
        for user in (team["owner"], team["admin"]):
            response = _read(client, user)
            assert response.status_code == 200, response.text
            actions = [item["action"] for item in response.json()["items"]]
            assert actions == ["service_token.created", "service_account.created"]

    def test_anyone_else_gets_a_403(self, client, db_session, team, propuestas):
        assert _read(client, team["ana"]).status_code == 403
        outsider = _person(db_session, "nobody@example.com", None)
        assert _read(client, outsider).status_code == 403
        assert client.get(AUDIT, headers=_api_key(db_session, team["owner"])).status_code == 403
        assert client.get(AUDIT).status_code == 401

    def test_a_service_token_is_refused(self, client, propuestas):
        assert not_for_services("GET", AUDIT)
        response = client.get(AUDIT, headers=_bearer(propuestas["token"]))
        assert response.status_code == 403
        assert response.json()["code"] == "service_account_not_allowed"

    def test_it_is_no_mcp_tool(self):
        pytest.importorskip("fastmcp")
        import asyncio

        from mcp_server.server import MCP_TOOL_NAMES, _build_mcp_server

        operation = app.openapi()["paths"][AUDIT]["get"]["operationId"]
        tools = {tool.name for tool in asyncio.run(_build_mcp_server().list_tools())}
        assert MCP_TOOL_NAMES.get(operation, operation) not in tools
        assert not [name for name in tools if "audit" in name]

    def test_an_item_with_the_people_and_link_looked_up(self, client, team, propuestas):
        made = _make_link(client, _for_ana(propuestas)).json()
        page = _read(client, team["owner"]).json()
        assert page["next_before"] is None
        created, token, account = page["items"]
        assert created["action"] == "url.created"
        assert (created["target_type"], created["target_id"]) == ("url", made["id"])
        assert created["short_code"] == made["short_code"]
        assert created["service_account"] == {
            "id": propuestas["account"]["id"],
            "display_name": "Propuestas Griddo",
            "deleted": False,
        }
        assert created["token_id"] == propuestas["issued"]["id"]
        assert created["actor"] is None
        assert created["on_behalf_of"] == {
            "id": str(team["ana"].id),
            "email": "ana.garcia@griddo.io",
            "name": "Ana García",
            "deleted": False,
        }
        assert created["at"].endswith("Z")
        assert set(created) == {
            "id",
            "at",
            "action",
            "target_type",
            "target_id",
            "short_code",
            "detail",
            "service_account",
            "token_id",
            "actor",
            "on_behalf_of",
        }
        assert token["action"] == "service_token.created"
        assert token["actor"] == {
            "id": str(team["owner"].id),
            "email": "owner@griddo.io",
            "name": "Olga Owner",
            "deleted": False,
        }
        assert token["short_code"] is None and token["on_behalf_of"] is None
        assert account["action"] == "service_account.created"

    def test_a_deleted_link_and_a_deleted_person(self, client, db_session, team, propuestas):
        carla = _person(db_session, "carla@griddo.io", OrgRole.MEMBER, "Carla", "Ruiz")
        headers = {**_bearer(propuestas["token"]), ON_BEHALF: "carla@griddo.io"}
        made = _make_link(client, headers).json()
        assert (
            client.delete(f"/api/v1/urls/{made['short_code']}", headers=headers).status_code == 204
        )
        assert db_session.query(URL).filter(URL.short_code == made["short_code"]).count() == 0
        db_session.query(OrganizationMember).filter(OrganizationMember.user_id == carla.id).delete()
        db_session.delete(carla)
        db_session.commit()

        items = _read(client, team["owner"]).json()["items"]
        deleted, created = items[0], items[1]
        assert (deleted["action"], created["action"]) == ("url.deleted", "url.created")
        for item in (deleted, created):
            assert item["target_id"] == made["id"]
            assert item["short_code"] is None
            assert item["on_behalf_of"] == {
                "id": str(carla.id),
                "email": None,
                "name": None,
                "deleted": True,
            }

    def test_a_removed_accounts_rows_stay_readable(self, client, team, propuestas):
        account_id = propuestas["account"]["id"]
        assert (
            client.delete(f"{BASE}/{account_id}", headers=_session(team["owner"])).status_code
            == 204
        )
        items = _read(client, team["owner"], account=account_id).json()["items"]
        assert items[0]["action"] == "service_account.removed"
        assert items[0]["service_account"]["display_name"] == "Propuestas Griddo"

    def test_another_organizations_rows_never_show(self, client, db_session, team, propuestas):
        elsewhere = _other_organization(client, db_session)
        mine = _read(client, team["owner"], limit=200).json()["items"]
        assert {item["service_account"]["id"] for item in mine} == {propuestas["account"]["id"]}
        theirs = _read(client, team["owner"], account=elsewhere["account"]["id"]).json()
        assert theirs == {"items": [], "next_before": None}
        their_own = _read(client, elsewhere["owner"]).json()["items"]
        assert {item["service_account"]["id"] for item in their_own} == {elsewhere["account"]["id"]}
        assert [item["action"] for item in their_own] == [
            "url.created",
            "service_token.created",
            "service_account.created",
        ]

    def test_filtered_by_account(self, client, team, propuestas):
        other = _create_account(client, team, name="Another")
        items = _read(client, team["owner"], account=other["id"]).json()["items"]
        assert [item["action"] for item in items] == ["service_account.created"]
        assert items[0]["service_account"]["id"] == other["id"]

    def test_paged_with_before(self, client, team, propuestas):
        service_headers = _bearer(propuestas["token"])
        for _ in range(4):
            assert _make_link(client, service_headers).status_code == 201
        everything = _read(client, team["owner"], limit=200).json()["items"]
        assert len(everything) == 6
        times = [item["at"] for item in everything]
        assert times == sorted(times, reverse=True)

        seen, before = [], None
        while True:
            params = {"limit": 4} if before is None else {"limit": 4, "before": before}
            page = _read(client, team["owner"], **params).json()
            seen += page["items"]
            before = page["next_before"]
            if before is None:
                break
            assert before == page["items"][-1]["at"]
        assert [item["id"] for item in seen] == [item["id"] for item in everything]

    def test_a_page_never_splits_one_instant(self, client, db_session, team, propuestas):
        _clear_audit(db_session)
        organization_id = _organization_id(db_session, team["owner"])
        account_id = uuid.UUID(propuestas["account"]["id"])
        newest, tied = datetime(2026, 10, 19, 10, 0, 3), datetime(2026, 10, 19, 10, 0, 2)
        oldest = datetime(2026, 10, 19, 10, 0, 1)
        for at in (newest, tied, tied, tied, oldest):
            db_session.add(
                AuditEvent(
                    at=at,
                    organization_id=organization_id,
                    service_account_id=account_id,
                    action="url.created",
                    target_type="url",
                    target_id=str(uuid.uuid4()),
                )
            )
        db_session.commit()
        first = _read(client, team["owner"], limit=2).json()
        assert len(first["items"]) == 1  # ends before the instant it would split
        assert first["next_before"] == "2026-10-19T10:00:03Z"
        second = _read(client, team["owner"], limit=2, before=first["next_before"]).json()
        assert len(second["items"]) == 3  # one instant fills it: all of it
        third = _read(client, team["owner"], limit=2, before=second["next_before"]).json()
        assert [item["at"] for item in third["items"]] == ["2026-10-19T10:00:01Z"]
        assert third["next_before"] is None

    def test_before_takes_an_offset(self, client, team, propuestas):
        future = _read(client, team["owner"], before="2999-01-01T02:00:00+02:00").json()
        assert len(future["items"]) == 2
        past = _read(client, team["owner"], before="2000-01-01T00:00:00Z").json()
        assert past == {"items": [], "next_before": None}

    @pytest.mark.parametrize(
        "params", [{"limit": 0}, {"limit": 201}, {"before": "yesterday"}, {"account": "audit"}]
    )
    def test_bad_parameters_are_a_422(self, client, team, propuestas, params):
        assert _read(client, team["owner"], **params).status_code == 422

    def test_a_service_action_with_detail(self, client, db_session, team, propuestas):
        """What T4's `record` wrote reads back as written: ids and field names."""
        account = db_session.get(User, uuid.UUID(propuestas["account"]["id"]))
        audit.record(
            db_session,
            acting=Acting(creator=account, service=account, token_id=None),
            action="campaign.updated",
            target_id=uuid.uuid4(),
            detail={"fields": ["tags"]},
        )
        db_session.commit()
        item = _read(client, team["owner"]).json()["items"][0]
        assert (item["action"], item["target_type"], item["short_code"]) == (
            "campaign.updated",
            "campaign",
            None,
        )
        assert item["detail"] == {"fields": ["tags"]}


class TestAttentionOnTheOrganization:
    """The menu's dot rides on GET /organization, which every dashboard page already loads."""

    def test_owners_and_admins_get_the_count_members_get_null(self, client, team, propuestas):
        for who, expected in (("owner", 0), ("admin", 0), ("ana", None)):
            body = client.get("/api/v1/organization", headers=_session(team[who])).json()
            assert body["service_accounts_attention"] == expected, who

    def test_a_token_unused_for_90_days_counts(self, client, team, propuestas, db_session):
        row = _row(db_session, propuestas["issued"]["id"])
        row.created_at = datetime.utcnow() - timedelta(days=100)
        db_session.commit()

        body = client.get("/api/v1/organization", headers=_session(team["owner"])).json()
        assert body["service_accounts_attention"] == 1
