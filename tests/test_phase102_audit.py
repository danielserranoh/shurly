"""
Phase 10.2 — the audit of what service accounts do (server/utils/audit.py).

- Every change a service account makes writes one `audit_events` row: the action
  (`<target>.<verb>`), the target's id, the service account, its token and the person it acted
  for, in the service account's organization.
- A person's own change writes none.
- The row is in the change's transaction: a refused or rolled-back change leaves none.
- `detail` holds ids and field names, never the values.
"""

from __future__ import annotations

import json
import uuid

import pytest

from server.core.models import URL, AuditEvent, OrganizationMember, OrgRole
from server.utils import audit
from server.utils.service_accounts import Acting
from tests.test_phase101_service_accounts import (
    ON_BEHALF,
    _bearer,
    _create_account,
    _for_ana,
    _issue,
    _make_link,
    _person,
    _session,
)

SECRET_TITLE = "Proposal for ACME, eyes only"
SECRET_TARGET = "https://acme-secret.example/landing"


def _rows(db_session) -> list[AuditEvent]:
    db_session.expire_all()
    return db_session.query(AuditEvent).order_by(AuditEvent.at, AuditEvent.action).all()


def _only(db_session) -> AuditEvent:
    rows = _rows(db_session)
    assert len(rows) == 1, [row.action for row in rows]
    return rows[0]


def _organization_id(db_session, team):
    return (
        db_session.query(OrganizationMember)
        .filter(OrganizationMember.user_id == team["owner"].id)
        .one()
        .organization_id
    )


def _clear(db_session) -> None:
    db_session.query(AuditEvent).delete()
    db_session.commit()


def _assert_by_service(row, db_session, team, propuestas, on_behalf=None) -> None:
    assert str(row.service_account_id) == propuestas["account"]["id"]
    assert str(row.token_id) == propuestas["issued"]["id"]
    assert row.organization_id == _organization_id(db_session, team)
    assert row.on_behalf_of_id == (on_behalf.id if on_behalf else None)
    assert row.actor_id is None


def _as_text(row: AuditEvent) -> str:
    return json.dumps(
        {column.name: getattr(row, column.name) for column in AuditEvent.__table__.columns},
        default=str,
    )


@pytest.fixture
def team(db_session):
    """As tests/test_phase101_service_accounts.py's: an owner, an admin, Ana and Bob."""
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


@pytest.fixture
def propuestas(client, team, db_session):
    """The service account, a `member`, and its token; the audit rows making them wrote, cleared."""
    account = _create_account(client, team)
    issued = _issue(client, team, account["id"])
    _clear(db_session)
    return {"account": account, "token": issued["token"], "issued": issued}


@pytest.fixture
def service(propuestas) -> dict:
    """The service token, acting for nobody."""
    return _bearer(propuestas["token"])


@pytest.fixture
def link(client, service, db_session) -> dict:
    """A link the service account made, and an audit emptied of its creation."""
    made = _make_link(client, service)
    assert made.status_code == 201, made.text
    _clear(db_session)
    return made.json()


def _tag(client, team, name="proposals") -> dict:
    made = client.post("/api/v1/tags", json={"name": name}, headers=_session(team["owner"]))
    assert made.status_code == 201, made.text
    return made.json()


def _campaign(client, headers) -> dict:
    made = client.post(
        "/api/v1/campaigns",
        json={
            "name": "Proposals",
            "original_url": "https://propuestas.griddo.io/p/3",
            "csv_data": "firstName\nLuis\nMar",
        },
        headers=headers,
    )
    assert made.status_code == 201, made.text
    return made.json()


# ---------------------------------------------------------------- Links


class TestLinks:
    def test_creating_a_link_for_a_person(self, client, team, propuestas, db_session):
        made = _make_link(client, _for_ana(propuestas)).json()
        row = _only(db_session)
        assert (row.action, row.target_type, row.target_id) == ("url.created", "url", made["id"])
        _assert_by_service(row, db_session, team, propuestas, on_behalf=team["ana"])
        assert row.detail is None

    def test_creating_a_custom_link_for_nobody(self, client, team, propuestas, service, db_session):
        made = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://propuestas.griddo.io/p/2", "custom_code": "acme-2026"},
            headers=service,
        )
        assert made.status_code == 201, made.text
        row = _only(db_session)
        assert (row.action, row.target_id) == ("url.created", made.json()["id"])
        _assert_by_service(row, db_session, team, propuestas)
        assert "acme-2026" not in _as_text(row)  # the id, never the code

    def test_updating_names_the_fields_never_the_values(
        self, client, team, propuestas, link, db_session
    ):
        headers = {**_bearer(propuestas["token"]), ON_BEHALF: "ana.garcia@griddo.io"}
        response = client.patch(
            f"/api/v1/urls/{link['short_code']}",
            json={"title": SECRET_TITLE, "forward_parameters": False},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        row = _only(db_session)
        assert (row.action, row.target_id) == ("url.updated", link["id"])
        assert row.detail == {"fields": ["forward_parameters", "title"]}
        _assert_by_service(row, db_session, team, propuestas, on_behalf=team["ana"])
        assert SECRET_TITLE not in _as_text(row)
        assert "ana.garcia" not in _as_text(row)

    def test_replacing_tags(self, client, team, propuestas, service, link, db_session):
        tag = _tag(client, team)
        _clear(db_session)
        response = client.patch(
            f"/api/v1/urls/{link['short_code']}/tags",
            json={"tag_ids": [tag["id"]]},
            headers=service,
        )
        assert response.status_code == 200, response.text
        row = _only(db_session)
        assert (row.action, row.target_id) == ("url.updated", link["id"])
        assert row.detail == {"fields": ["tags"], "tag_ids": [tag["id"]]}
        assert "proposals" not in _as_text(row)

    def test_deleting(self, client, team, propuestas, service, link, db_session):
        response = client.delete(f"/api/v1/urls/{link['short_code']}", headers=service)
        assert response.status_code == 204
        row = _only(db_session)
        assert (row.action, row.target_type, row.target_id) == ("url.deleted", "url", link["id"])
        _assert_by_service(row, db_session, team, propuestas)

    def test_bulk_tags_one_row_per_link_changed(
        self, client, team, propuestas, service, link, db_session
    ):
        other = _make_link(client, service).json()
        tag = _tag(client, team)
        _clear(db_session)
        body = {"short_codes": [link["short_code"], other["short_code"]], "tag_ids": [tag["id"]]}
        response = client.post("/api/v1/urls/bulk/tags", json=body, headers=service)
        assert response.status_code == 200, response.text
        rows = _rows(db_session)
        assert sorted(row.target_id for row in rows) == sorted([link["id"], other["id"]])
        assert {row.action for row in rows} == {"url.updated"}
        assert all(row.detail == {"fields": ["tags"], "tag_ids": [tag["id"]]} for row in rows)
        # Tagging again changes nothing, and writes nothing.
        _clear(db_session)
        assert client.post("/api/v1/urls/bulk/tags", json=body, headers=service).status_code == 200
        assert _rows(db_session) == []

    def test_bulk_tags_names_the_person_acted_for(self, client, team, propuestas, link, db_session):
        tag = _tag(client, team)
        _clear(db_session)
        response = client.post(
            "/api/v1/urls/bulk/tags",
            json={"short_codes": [link["short_code"]], "tag_ids": [tag["id"]]},
            headers=_for_ana(propuestas),
        )
        assert response.status_code == 200, response.text
        _assert_by_service(_only(db_session), db_session, team, propuestas, on_behalf=team["ana"])


# ---------------------------------------------------------------- Redirect rules


class TestRedirectRules:
    def test_create_update_delete(self, client, team, propuestas, service, link, db_session):
        base = f"/api/v1/urls/{link['short_code']}/rules"
        made = client.post(
            base,
            json={
                "priority": 5,
                "conditions": [{"type": "language", "value": "es"}],
                "target_url": SECRET_TARGET,
            },
            headers=service,
        )
        assert made.status_code == 201, made.text
        rule_id = made.json()["id"]
        row = _only(db_session)
        assert (row.action, row.target_type, row.target_id) == (
            "redirect_rule.created",
            "redirect_rule",
            rule_id,
        )
        assert row.detail == {"url_id": link["id"]}
        _assert_by_service(row, db_session, team, propuestas)
        assert SECRET_TARGET not in _as_text(row)

        _clear(db_session)
        headers = {**service, ON_BEHALF: "ana.garcia@griddo.io"}
        changed = client.patch(
            f"{base}/{rule_id}", json={"target_url": SECRET_TARGET + "/2"}, headers=headers
        )
        assert changed.status_code == 200, changed.text
        row = _only(db_session)
        assert (row.action, row.target_id) == ("redirect_rule.updated", rule_id)
        assert row.detail == {"url_id": link["id"], "fields": ["target_url"]}
        _assert_by_service(row, db_session, team, propuestas, on_behalf=team["ana"])
        assert SECRET_TARGET not in _as_text(row)

        _clear(db_session)
        assert client.delete(f"{base}/{rule_id}", headers=service).status_code == 204
        row = _only(db_session)
        assert (row.action, row.target_id) == ("redirect_rule.deleted", rule_id)
        assert row.detail == {"url_id": link["id"]}

    def test_a_rule_not_found_writes_nothing(self, client, service, link, db_session):
        missing = f"/api/v1/urls/{link['short_code']}/rules/{uuid.uuid4()}"
        assert client.delete(missing, headers=service).status_code == 404
        assert client.patch(missing, json={"priority": 1}, headers=service).status_code == 404
        assert _rows(db_session) == []


# ---------------------------------------------------------------- Campaigns


class TestCampaigns:
    def test_create_tag_delete(self, client, team, propuestas, db_session):
        made = _campaign(client, _for_ana(propuestas))
        row = _only(db_session)
        assert (row.action, row.target_type, row.target_id) == (
            "campaign.created",
            "campaign",
            made["id"],
        )
        _assert_by_service(row, db_session, team, propuestas, on_behalf=team["ana"])
        assert "Luis" not in _as_text(row) and "Proposals" not in _as_text(row)

        # Its own campaign: one made for Ana is hers to change, not a member service's.
        service = _bearer(propuestas["token"])
        made = _campaign(client, service)
        tag = _tag(client, team)
        _clear(db_session)
        tagged = client.patch(
            f"/api/v1/campaigns/{made['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=service
        )
        assert tagged.status_code == 200, tagged.text
        row = _only(db_session)
        assert (row.action, row.target_id) == ("campaign.updated", made["id"])
        assert row.detail == {"fields": ["tags"], "tag_ids": [tag["id"]]}
        _assert_by_service(row, db_session, team, propuestas)

        _clear(db_session)
        assert client.delete(f"/api/v1/campaigns/{made['id']}", headers=service).status_code == 204
        row = _only(db_session)
        assert (row.action, row.target_id) == ("campaign.deleted", made["id"])

    def test_a_refused_campaign_writes_nothing(self, client, propuestas, db_session):
        response = client.post(
            "/api/v1/campaigns",
            json={"name": "x", "original_url": "https://propuestas.griddo.io/", "csv_data": "a\n1"},
            headers={**_bearer(propuestas["token"]), ON_BEHALF: "nobody@griddo.io"},
        )
        assert response.status_code == 422
        assert _rows(db_session) == []


# ---------------------------------------------------------------- Tags


class TestTags:
    def test_create_update_delete(self, client, team, propuestas, service, db_session):
        made = client.post("/api/v1/tags", json={"name": "q4-acme"}, headers=service)
        assert made.status_code == 201, made.text
        tag_id = made.json()["id"]
        row = _only(db_session)
        assert (row.action, row.target_type, row.target_id) == ("tag.created", "tag", tag_id)
        _assert_by_service(row, db_session, team, propuestas)
        assert "acme" not in _as_text(row)

        _clear(db_session)
        renamed = client.patch(
            f"/api/v1/tags/{tag_id}", json={"name": "q4-globex"}, headers=_for_ana(propuestas)
        )
        assert renamed.status_code == 200, renamed.text
        row = _only(db_session)
        assert (row.action, row.target_id, row.detail) == (
            "tag.updated",
            tag_id,
            {"fields": ["name"]},
        )
        _assert_by_service(row, db_session, team, propuestas, on_behalf=team["ana"])
        assert "globex" not in _as_text(row)

        _clear(db_session)
        assert client.delete(f"/api/v1/tags/{tag_id}", headers=service).status_code == 204
        row = _only(db_session)
        assert (row.action, row.target_id) == ("tag.deleted", tag_id)

    def test_a_refused_tag_writes_nothing(self, client, team, service, db_session):
        _tag(client, team, "taken")
        _clear(db_session)
        assert (
            client.post("/api/v1/tags", json={"name": "taken"}, headers=service).status_code == 400
        )
        assert _rows(db_session) == []


# ---------------------------------------------------------------- People


def test_a_persons_own_changes_write_nothing(client, team, db_session):
    ana = _session(team["ana"])
    made = _make_link(client, ana).json()
    code = made["short_code"]
    tag = _tag(client, team)
    assert client.patch(f"/api/v1/urls/{code}", json={"title": "t"}, headers=ana).status_code == 200
    assert (
        client.patch(f"/api/v1/urls/{code}/tags", json={"tag_ids": [tag["id"]]}, headers=ana)
    ).status_code == 200
    bulk = {"short_codes": [code], "tag_ids": [tag["id"]]}
    assert client.post("/api/v1/urls/bulk/tags", json=bulk, headers=ana).status_code == 200
    rule = client.post(
        f"/api/v1/urls/{code}/rules",
        json={"conditions": [{"type": "device", "value": "ios"}], "target_url": SECRET_TARGET},
        headers=ana,
    ).json()
    assert (
        client.patch(f"/api/v1/urls/{code}/rules/{rule['id']}", json={"priority": 2}, headers=ana)
    ).status_code == 200
    assert client.delete(f"/api/v1/urls/{code}/rules/{rule['id']}", headers=ana).status_code == 204
    campaign = _campaign(client, ana)
    assert (
        client.patch(
            f"/api/v1/campaigns/{campaign['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=ana
        )
    ).status_code == 200
    assert client.delete(f"/api/v1/campaigns/{campaign['id']}", headers=ana).status_code == 204
    assert (
        client.patch(f"/api/v1/tags/{tag['id']}", json={"name": "x2"}, headers=ana).status_code
        == 200
    )
    assert client.delete(f"/api/v1/tags/{tag['id']}", headers=ana).status_code == 204
    assert client.delete(f"/api/v1/urls/{code}", headers=ana).status_code == 204
    assert _rows(db_session) == []


def test_a_person_sending_the_header_on_a_route_that_ignored_it_still_works(
    client, team, db_session
):
    """Tags, rules, campaign delete and tags, bulk tags: no new 403 for a person (10.2)."""
    headers = {**_session(team["ana"]), ON_BEHALF: "bob@griddo.io"}
    assert client.post("/api/v1/tags", json={"name": "fine"}, headers=headers).status_code == 201
    assert _rows(db_session) == []


# ---------------------------------------------------------------- The transaction


class TestTransaction:
    def test_a_refused_link_writes_nothing(self, client, propuestas, db_session):
        response = _make_link(
            client, {**_bearer(propuestas["token"]), ON_BEHALF: "nobody@griddo.io"}
        )
        assert response.status_code == 422
        assert _rows(db_session) == []

    def test_a_refused_tag_change_writes_nothing(self, client, service, link, db_session):
        response = client.patch(
            f"/api/v1/urls/{link['short_code']}/tags",
            json={"tag_ids": [str(uuid.uuid4())]},
            headers=service,
        )
        assert response.status_code == 400
        assert _rows(db_session) == []

    def test_a_change_whose_commit_fails_leaves_no_row(
        self, client, propuestas, service, db_session, monkeypatch
    ):
        def fail():
            raise RuntimeError("the database went away")

        monkeypatch.setattr(db_session, "commit", fail)
        with pytest.raises(RuntimeError):
            _make_link(client, service)
        monkeypatch.undo()
        db_session.rollback()  # what closing the request's session does
        assert _rows(db_session) == []
        assert db_session.query(URL).count() == 0

    def test_record_is_in_the_callers_transaction(self, db_session, team, propuestas):
        account = db_session.get(type(team["ana"]), uuid.UUID(propuestas["account"]["id"]))
        acting = Acting(creator=account, service=account, token_id=None)
        row = audit.record(db_session, acting=acting, action="url.deleted", target_id=uuid.uuid4())
        assert row is not None and row in db_session.new  # added, not flushed or committed
        db_session.rollback()
        assert _rows(db_session) == []


# ---------------------------------------------------------------- The helpers


def test_record_writes_nothing_for_a_person(db_session, team):
    acting = Acting(creator=team["ana"])
    assert audit.record(db_session, acting=acting, action="url.created", target_id="x") is None
    assert not any(isinstance(added, AuditEvent) for added in db_session.new)


def test_an_action_is_target_dot_verb(db_session, team):
    with pytest.raises(ValueError):
        audit.record(db_session, acting=Acting(creator=team["ana"]), action="created", target_id=1)


def test_an_account_event_names_the_owner_who_made_it(db_session, team, propuestas):
    organization_id = _organization_id(db_session, team)
    account_id = uuid.UUID(propuestas["account"]["id"])
    token_id = uuid.UUID(propuestas["issued"]["id"])
    audit.record_account_event(
        db_session,
        actor=team["owner"],
        account_id=account_id,
        organization_id=organization_id,
        action="service_token.renewed",
        token_id=token_id,
        detail={"replaced_token_id": str(uuid.uuid4())},
    )
    db_session.commit()
    row = _only(db_session)
    assert (row.target_type, row.target_id) == ("service_token", str(token_id))
    assert (row.actor_id, row.service_account_id, row.token_id) == (
        team["owner"].id,
        account_id,
        token_id,
    )
    assert row.on_behalf_of_id is None and row.organization_id == organization_id
