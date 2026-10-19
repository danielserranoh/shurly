"""
Phase 10.3 — the routes of links managed by their service account
(`_board/plan_managed-links-propuestas.md`, T2; the rule itself is
tests/test_phase103_managed_rule.py).

A link Propuestas made for Ana is managed by Propuestas:
- **Changing it** (DELETE, PATCH, refresh-preview, the redirect rules): only Propuestas. Anyone
  else, owners included, gets a 403 `managed_link_protected`.
- **Its tags:** by the rule before, the person it was made for, admins, owners and Propuestas.
- **Its destination** (and its rules' targets): Propuestas and the owners read it, everyone else
  a mask, and search doesn't match it for them.
- **The list** filters by `managed=exclude|only` and `managed_by=<id>`; `/urls/managers` gives
  the tabs.
- **An owner deletes it anyway** with a reason (`override-delete`), audited; never a service, never
  through the MCP.
- **Propuestas does everything it did in v1.**
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from server.core.config import settings
from server.core.models import URL, AuditEvent, OrgRole, RedirectRule, User, Visitor
from server.core.models.url import URLType
from server.utils import organization as org_service
from server.utils.domain import get_or_create_default_domain
from tests.test_phase101_service_accounts import (
    ON_BEHALF,
    _api_key,
    _bearer,
    _create_account,
    _events,
    _issue,
    _make_link,
    _person,
    _session,
)

URLS = "/api/v1/urls"
SECRET = "https://propuestas.griddo.io/p/abc?t=s3cr3t"
MASK = "https://propuestas.griddo.io/…"
RULE_TARGET = "https://propuestas.griddo.io/p/abc/en?t=s3cr3t"
IOS = [{"type": "device", "value": "ios"}]
REASON = "The client withdrew; Propuestas is down"

# Who reads the managed link's destination, and who gets its mask.
SEE = ["owner", "manager"]
MASKED = ["admin", "ana", "bob", "other_service", "other_admin_service"]
# Everyone but its manager: owners, admins, the person it was made for, members, other services.
NOT_THE_MANAGER = ["owner", "admin", "ana", "bob", "other_service", "other_admin_service"]


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(settings, "service_account_rate_limit_per_minute", 0)


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


def _account(client, db_session, team, name: str, role: str = "member") -> tuple[User, str]:
    account = _create_account(client, team, role=role, name=name)
    token = _issue(client, team, account["id"])["token"]
    return db_session.get(User, uuid.UUID(account["id"])), token


@pytest.fixture
def world(client, db_session, team):
    """Propuestas (a member service account) made a link for Ana, with a redirect rule: managed.
    Ana made one herself: ordinary. Two other service accounts, a member and an admin."""
    propuestas, token = _account(client, db_session, team, "Propuestas Griddo")
    other, other_token = _account(client, db_session, team, "Another integration")
    other_admin, other_admin_token = _account(
        client, db_session, team, "An admin integration", role="admin"
    )
    manager = _bearer(token)

    made = _make_link(client, {**manager, ON_BEHALF: "ana.garcia@griddo.io"}, url=SECRET)
    assert made.status_code == 201, made.text
    code = made.json()["short_code"]
    rule = client.post(
        f"{URLS}/{code}/rules", json={"conditions": IOS, "target_url": RULE_TARGET}, headers=manager
    )
    assert rule.status_code == 201, rule.text
    mine = _make_link(client, _session(team["ana"]), url="https://example.com/ana?x=1")
    assert mine.status_code == 201, mine.text

    headers = {who: _session(team[who]) for who in ("owner", "admin", "ana", "bob")}
    headers |= {
        "manager": manager,
        "other_service": _bearer(other_token),
        "other_admin_service": _bearer(other_admin_token),
    }
    return {
        **team,
        "manager": propuestas,
        "other_service": other,
        "other_admin_service": other_admin,
        "headers": headers,
        "code": code,
        "rule_id": rule.json()["id"],
        "ordinary": mine.json()["short_code"],
    }


def _link(db_session, code: str) -> URL | None:
    db_session.expire_all()
    return db_session.query(URL).filter(URL.short_code == code).one_or_none()


def _item(listed: dict, code: str) -> dict:
    [item] = [link for link in listed["urls"] if link["short_code"] == code]
    return item


def _codes(response) -> list[str]:
    assert response.status_code == 200, response.text
    return sorted(link["short_code"] for link in response.json()["urls"])


# ---------------------------------------------------------------- Changing it


CHANGES = [
    ("DELETE", "", None),
    ("PATCH", "", {"title": "Mine"}),
    ("PATCH", "", {"valid_until": "2030-01-01T00:00:00Z"}),
    ("POST", "/refresh-preview", None),
    ("POST", "/rules", {"conditions": IOS, "target_url": "https://example.com/x"}),
    ("PATCH", "/rules/{rule_id}", {"target_url": "https://example.com/x"}),
    ("DELETE", "/rules/{rule_id}", None),
]


class TestChangingIt:
    @pytest.mark.parametrize("who", NOT_THE_MANAGER)
    @pytest.mark.parametrize("method, path, body", CHANGES)
    def test_only_its_manager(self, client, db_session, world, who, method, path, body):
        route = f"{URLS}/{world['code']}{path.format(rule_id=world['rule_id'])}"
        response = client.request(method, route, json=body, headers=world["headers"][who])
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "managed_link_protected"
        assert "Propuestas Griddo" in response.json()["detail"]

        link = _link(db_session, world["code"])
        assert link is not None and link.title is None and link.valid_until is None
        [rule] = db_session.query(RedirectRule).filter(RedirectRule.url_id == link.id).all()
        assert rule.target_url == RULE_TARGET

    @pytest.mark.parametrize("method, path, body", CHANGES)
    def test_its_manager_changes_it(self, client, world, method, path, body):
        route = f"{URLS}/{world['code']}{path.format(rule_id=world['rule_id'])}"
        response = client.request(method, route, json=body, headers=world["headers"]["manager"])
        assert response.status_code in (200, 201, 204), response.text

    def test_an_ordinary_link_is_as_before(self, client, world):
        ordinary = f"{URLS}/{world['ordinary']}"
        bob = client.patch(ordinary, json={"title": "Bob's"}, headers=world["headers"]["bob"])
        assert bob.status_code == 403
        assert bob.json().get("code") is None
        for who in ("ana", "admin", "owner"):
            changed = client.patch(ordinary, json={"title": who}, headers=world["headers"][who])
            assert changed.status_code == 200, (who, changed.text)
        assert client.delete(ordinary, headers=world["headers"]["admin"]).status_code == 204


class TestTags:
    @pytest.fixture
    def tag(self, client, world):
        made = client.post("/api/v1/tags", json={"name": "Hot"}, headers=world["headers"]["bob"])
        assert made.status_code == 201, made.text
        return made.json()["id"]

    @pytest.mark.parametrize("who", ["ana", "admin", "owner", "manager", "other_admin_service"])
    def test_who_tagged_it_before_still_does(self, client, world, tag, who):
        response = client.patch(
            f"{URLS}/{world['code']}/tags", json={"tag_ids": [tag]}, headers=world["headers"][who]
        )
        assert response.status_code == 200, response.text
        assert [t["id"] for t in response.json()["tags"]] == [tag]

    @pytest.mark.parametrize("who", ["bob", "other_service"])
    def test_who_didnt_still_doesnt(self, client, world, tag, who):
        response = client.patch(
            f"{URLS}/{world['code']}/tags", json={"tag_ids": [tag]}, headers=world["headers"][who]
        )
        assert response.status_code == 403
        assert response.json().get("code") is None  # the plain 403: it isn't about the lock

    def test_bulk_tags(self, client, world, tag, db_session):
        codes = [world["code"], world["ordinary"]]
        body = {"short_codes": codes, "tag_ids": [tag]}
        for who in ("ana", "admin", "owner"):
            response = client.post(f"{URLS}/bulk/tags", json=body, headers=world["headers"][who])
            assert response.status_code == 200, response.text
            assert response.json() == {"updated": 2, "failed": []}, who
        assert [str(t.id) for t in _link(db_session, world["code"]).tags] == [tag]

        refused = client.post(f"{URLS}/bulk/tags", json=body, headers=world["headers"]["bob"])
        assert refused.json()["updated"] == 0
        assert sorted(f["short_code"] for f in refused.json()["failed"]) == sorted(codes)

    def test_the_manager_bulk_tags_its_own_but_not_anas(self, client, world, tag):
        body = {"short_codes": [world["code"], world["ordinary"]], "tag_ids": [tag]}
        response = client.post(f"{URLS}/bulk/tags", json=body, headers=world["headers"]["manager"])
        assert response.json()["updated"] == 1
        assert [f["short_code"] for f in response.json()["failed"]] == [world["ordinary"]]


# ---------------------------------------------------------------- Reading it


class TestMasking:
    @pytest.mark.parametrize("who", SEE + MASKED)
    def test_get_list_and_rules(self, client, world, who):
        expected = SECRET if who in SEE else MASK
        expected_rule = RULE_TARGET if who in SEE else MASK
        headers = world["headers"][who]
        manager = {"id": str(world["manager"].id), "display_name": "Propuestas Griddo"}

        one = client.get(f"{URLS}/{world['code']}", headers=headers)
        assert one.status_code == 200, one.text
        assert one.json()["original_url"] == expected
        assert one.json()["managed_by"] == manager

        listed = client.get(URLS, headers=headers).json()
        assert _item(listed, world["code"])["original_url"] == expected
        assert _item(listed, world["code"])["managed_by"] == manager
        ordinary = _item(listed, world["ordinary"])
        assert ordinary["original_url"] == "https://example.com/ana?x=1"
        assert ordinary["managed_by"] is None

        rules = client.get(f"{URLS}/{world['code']}/rules", headers=headers)
        assert [rule["target_url"] for rule in rules.json()] == [expected_rule]

        if who in MASKED:
            assert "s3cr3t" not in one.text + client.get(URLS, headers=headers).text + rules.text

    def test_a_campaign_link_a_service_made_isnt_masked(self, client, db_session, world):
        _campaign_link(db_session, world)
        listed = client.get(URLS, headers=world["headers"]["bob"]).json()
        item = _item(listed, "camp01")
        assert item["original_url"] == SECRET
        assert item["managed_by"] is None
        assert item["via_service_account"]["display_name"] == "Propuestas Griddo"

    def test_rules_on_an_ordinary_link_arent_masked(self, client, world):
        made = client.post(
            f"{URLS}/{world['ordinary']}/rules",
            json={"conditions": IOS, "target_url": "https://example.com/ios?k=1"},
            headers=world["headers"]["ana"],
        )
        assert made.json()["target_url"] == "https://example.com/ios?k=1"
        rules = client.get(f"{URLS}/{world['ordinary']}/rules", headers=world["headers"]["bob"])
        assert [r["target_url"] for r in rules.json()] == ["https://example.com/ios?k=1"]


class TestSearch:
    @pytest.mark.parametrize("who", MASKED)
    def test_a_hidden_destination_doesnt_match(self, client, world, who):
        found = client.get(URLS, params={"q": "s3cr3t"}, headers=world["headers"][who])
        assert _codes(found) == []
        assert found.json()["total"] == 0

    @pytest.mark.parametrize("who", SEE)
    def test_a_destination_one_reads_does(self, client, world, who):
        found = client.get(URLS, params={"q": "s3cr3t"}, headers=world["headers"][who])
        assert _codes(found) == [world["code"]]
        assert found.json()["total"] == 1

    def test_its_title_and_code_still_match(self, client, world):
        titled = client.patch(
            f"{URLS}/{world['code']}",
            json={"title": "Proposal for Acme"},
            headers=world["headers"]["manager"],
        )
        assert titled.status_code == 200, titled.text
        bob = world["headers"]["bob"]
        assert _codes(client.get(URLS, params={"q": "acme"}, headers=bob)) == [world["code"]]
        assert _codes(client.get(URLS, params={"q": world["code"]}, headers=bob)) == [world["code"]]

    def test_an_ordinary_destination_still_matches(self, client, world):
        found = client.get(URLS, params={"q": "example.com/ana"}, headers=world["headers"]["bob"])
        assert _codes(found) == [world["ordinary"]]


# ---------------------------------------------------------------- The list's params


def _campaign_link(db_session, world) -> URL:
    """A campaign link Propuestas made: a campaign link, not managed."""
    organization = org_service.get_or_create_default_organization(db_session)
    url = URL(
        short_code="camp01",
        original_url=SECRET,
        url_type=URLType.CAMPAIGN,
        created_by=world["ana"].id,
        organization_id=organization.id,
        via_service_account_id=world["manager"].id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


class TestListParams:
    def test_each(self, client, db_session, world):
        _campaign_link(db_session, world)
        bob = world["headers"]["bob"]
        managed, ordinary = world["code"], world["ordinary"]

        def codes(**params):
            return _codes(client.get(URLS, params=params, headers=bob))

        assert codes() == sorted([managed, ordinary, "camp01"])  # everything, as before
        assert codes(managed="exclude") == sorted([ordinary, "camp01"])
        assert codes(managed="only") == [managed]
        assert codes(managed_by=str(world["manager"].id)) == [managed]
        assert codes(managed_by=str(world["other_service"].id)) == []
        assert codes(managed_by=str(uuid.uuid4())) == []
        assert codes(managed="exclude", managed_by=str(world["manager"].id)) == []
        # `via_service_account` works as it did: campaign links included.
        assert codes(via_service_account=str(world["manager"].id)) == sorted([managed, "camp01"])

    def test_total_counts_the_filtered(self, client, world):
        response = client.get(URLS, params={"managed": "only"}, headers=world["headers"]["bob"])
        assert response.json()["total"] == 1

    @pytest.mark.parametrize(
        "params", [{"managed": "all"}, {"managed": ""}, {"managed_by": "propuestas"}]
    )
    def test_bad_values_are_422(self, client, world, params):
        assert client.get(URLS, params=params, headers=world["headers"]["bob"]).status_code == 422


# ---------------------------------------------------------------- GET /urls/managers


class TestManagers:
    @pytest.fixture
    def more(self, client, db_session, world):
        """Another integration manages two links; Propuestas one more, personal to the owner
        (made by hand: a service's own are always the organization's), which only she sees."""
        for n in range(2):
            made = _make_link(
                client, world["headers"]["other_service"], url=f"https://other.example/{n}"
            )
            assert made.status_code == 201, made.text
        hidden = URL(
            short_code="hidden1",
            original_url=SECRET,
            url_type=URLType.STANDARD,
            created_by=world["owner"].id,
            organization_id=None,
            via_service_account_id=world["manager"].id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
        db_session.add(hidden)
        _campaign_link(db_session, world)  # not managed: not counted
        return world

    def _managers(self, client, headers) -> list[dict]:
        response = client.get(f"{URLS}/managers", headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    @pytest.mark.parametrize("who", ["admin", "ana", "bob", "manager", "other_service"])
    def test_by_name_with_the_links_one_sees(self, client, more, who):
        assert self._managers(client, more["headers"][who]) == [
            {
                "id": str(more["other_service"].id),
                "display_name": "Another integration",
                "link_count": 2,
            },
            {
                "id": str(more["manager"].id),
                "display_name": "Propuestas Griddo",
                "link_count": 1,
            },
        ]

    def test_the_owner_counts_her_personal_one_too(self, client, more):
        counts = {
            row["display_name"]: row["link_count"]
            for row in self._managers(client, more["headers"]["owner"])
        }
        assert counts == {"Another integration": 2, "Propuestas Griddo": 2}

    def test_someone_outside_the_organization_sees_none(self, client, more, auth_headers):
        assert self._managers(client, auth_headers) == []

    def test_none_without_managed_links(self, client, team):
        assert self._managers(client, _session(team["bob"])) == []

    def test_a_removed_account_still_manages_its_links(self, client, world):
        removed = client.delete(
            f"/api/v1/service-accounts/{world['manager'].id}", headers=world["headers"]["owner"]
        )
        assert removed.status_code == 204, removed.text
        assert [row["display_name"] for row in self._managers(client, world["headers"]["bob"])] == [
            "Propuestas Griddo"
        ]

    def test_it_doesnt_shadow_the_list_or_a_link(self, client, world):
        bob = world["headers"]["bob"]
        assert client.get(URLS, headers=bob).json()["total"] == 2
        assert client.get(f"{URLS}/{world['code']}", headers=bob).status_code == 200


# ---------------------------------------------------------------- The override


def _override(client, code: str, headers: dict, reason=REASON):
    body = {} if reason is None else {"reason": reason}
    return client.post(f"{URLS}/{code}/override-delete", json=body, headers=headers)


class TestOverride:
    def test_an_owner_deletes_it_and_the_audit_says_who_and_why(
        self, client, db_session, world, capsys
    ):
        link = _link(db_session, world["code"])
        link_id, organization_id = link.id, link.organization_id
        db_session.add(Visitor(url_id=link_id, short_code=world["code"], ip="203.0.113.0"))
        db_session.commit()
        db_session.query(AuditEvent).delete()
        db_session.commit()
        capsys.readouterr()

        response = _override(client, world["code"], world["headers"]["owner"], f"  {REASON}  ")
        assert response.status_code == 204, response.text
        assert response.content == b""

        assert _link(db_session, world["code"]) is None
        assert db_session.query(Visitor).filter(Visitor.url_id == link_id).count() == 0
        assert db_session.query(RedirectRule).filter(RedirectRule.url_id == link_id).count() == 0

        [row] = db_session.query(AuditEvent).all()
        assert row.action == "url.deleted"
        assert row.target_type == "url"
        assert row.target_id == str(link_id)
        assert row.service_account_id == world["manager"].id
        assert row.actor_id == world["owner"].id
        assert row.organization_id == organization_id
        assert row.token_id is None and row.on_behalf_of_id is None
        assert row.detail == {"override": True, "reason": REASON}  # stripped

        err = capsys.readouterr().err
        [event] = _events(err, "url.override_deleted")
        assert event["url_id"] == str(link_id)
        assert event["actor_id"] == str(world["owner"].id)
        assert event["service_account_id"] == str(world["manager"].id)
        assert REASON not in err  # nowhere in the logs
        assert world["code"] not in str(event)  # ids only (the request's own line has its path)

    def test_the_audit_shows_it(self, client, world):
        assert _override(client, world["code"], world["headers"]["owner"]).status_code == 204
        audit = client.get("/api/v1/service-accounts/audit", headers=world["headers"]["owner"])
        assert audit.status_code == 200, audit.text
        [event] = [
            e
            for e in audit.json()["items"]
            if e["action"] == "url.deleted" and (e.get("detail") or {}).get("override")
        ]
        assert event["detail"]["reason"] == REASON
        assert event["actor"]["email"] == "owner@griddo.io"
        assert event["service_account"]["display_name"] == "Propuestas Griddo"

    def test_with_the_owners_api_key(self, client, db_session, world):
        headers = _api_key(db_session, world["owner"])
        assert _override(client, world["code"], headers).status_code == 204

    @pytest.mark.parametrize("who", ["admin", "ana", "bob"])
    def test_anyone_but_an_owner_is_refused(self, client, db_session, world, who):
        response = _override(client, world["code"], world["headers"][who])
        assert response.status_code == 403, response.text
        assert _link(db_session, world["code"]) is not None
        assert (
            db_session.query(AuditEvent)
            .filter(AuditEvent.actor_id.isnot(None))
            .filter(AuditEvent.action == "url.deleted")
            .count()
            == 0
        )

    @pytest.mark.parametrize("who", ["manager", "other_service", "other_admin_service"])
    def test_never_a_service(self, client, db_session, world, who):
        response = _override(client, world["code"], world["headers"][who])
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "service_account_not_allowed"
        assert _link(db_session, world["code"]) is not None

    def test_an_unmanaged_link_is_deleted_with_delete(self, client, db_session, world):
        response = _override(client, world["ordinary"], world["headers"]["owner"])
        assert response.status_code == 400
        assert "DELETE" in response.json()["detail"]
        assert _link(db_session, world["ordinary"]) is not None

    def test_a_campaign_link_isnt_managed(self, client, db_session, world):
        _campaign_link(db_session, world)
        assert _override(client, "camp01", world["headers"]["owner"]).status_code == 400

    @pytest.mark.parametrize(
        "reason", [None, "", "too short", "  short   ", "          ", "x" * 501, 42]
    )
    def test_a_reason_of_10_to_500_characters(self, client, db_session, world, reason):
        response = _override(client, world["code"], world["headers"]["owner"], reason)
        assert response.status_code == 422, response.text
        assert _link(db_session, world["code"]) is not None

    @pytest.mark.parametrize("reason", ["x" * 10, "x" * 500])
    def test_the_bounds(self, client, world, reason):
        assert _override(client, world["code"], world["headers"]["owner"], reason).status_code == (
            204
        )

    def test_a_link_one_cant_see_is_a_404(self, client, world, auth_headers):
        assert _override(client, world["code"], auth_headers).status_code == 404

    def test_an_owner_still_cant_delete_it_with_delete(self, client, db_session, world):
        response = client.delete(f"{URLS}/{world['code']}", headers=world["headers"]["owner"])
        assert response.status_code == 403
        assert response.json()["code"] == "managed_link_protected"
        assert _link(db_session, world["code"]) is not None


class TestMcp:
    @pytest.fixture(scope="class")
    def tools(self):
        pytest.importorskip("fastmcp")
        from mcp_server.server import _build_mcp_server

        return {tool.name: tool for tool in asyncio.run(_build_mcp_server().list_tools())}

    def test_the_override_isnt_a_tool(self, tools):
        assert not {name for name in tools if "override" in name}

    def test_the_managers_are(self, tools):
        assert "list_link_managers" in tools

    def test_list_urls_takes_the_new_params(self, tools):
        properties = tools["list_urls"].parameters["properties"]
        assert {"managed", "managed_by", "via_service_account"} <= set(properties)


# ---------------------------------------------------------------- Propuestas, as in v1


class TestThePropuestasAccountAsInV1:
    """Everything Propuestas did before 10.3, it still does, and it reads its destinations."""

    @pytest.mark.parametrize("on_behalf", [True, False])
    def test_create_change_rules_tags_and_delete(self, client, world, on_behalf):
        service = world["headers"]["manager"]
        creating = {**service, ON_BEHALF: "ana.garcia@griddo.io"} if on_behalf else service

        made = _make_link(client, creating, url=SECRET)
        assert made.status_code == 201, made.text
        assert made.json()["original_url"] == SECRET
        assert made.json()["managed_by"]["id"] == str(world["manager"].id)
        code = made.json()["short_code"]
        custom = client.post(
            f"{URLS}/custom", json={"url": SECRET, "custom_code": "acme-ana"}, headers=creating
        )
        assert custom.status_code == 201, custom.text
        assert custom.json()["original_url"] == SECRET

        changed = client.patch(
            f"{URLS}/{code}",
            json={"valid_until": "2030-01-01T00:00:00Z"},
            headers=creating,  # with the header too, as Propuestas sends it
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["valid_until"].startswith("2030-01-01")
        assert changed.json()["original_url"] == SECRET

        rule = client.post(
            f"{URLS}/{code}/rules",
            json={"conditions": IOS, "target_url": RULE_TARGET},
            headers=service,
        )
        assert rule.status_code == 201, rule.text
        assert rule.json()["target_url"] == RULE_TARGET
        rule_path = f"{URLS}/{code}/rules/{rule.json()['id']}"
        updated = client.patch(rule_path, json={"priority": 3}, headers=service)
        assert updated.status_code == 200 and updated.json()["target_url"] == RULE_TARGET
        listed_rules = client.get(f"{URLS}/{code}/rules", headers=service).json()
        assert [r["target_url"] for r in listed_rules] == [RULE_TARGET]
        assert client.delete(rule_path, headers=service).status_code == 204

        assert client.get(f"{URLS}/{code}", headers=service).json()["original_url"] == SECRET
        mine = client.get(URLS, params={"managed_by": str(world["manager"].id)}, headers=service)
        assert {link["original_url"] for link in mine.json()["urls"]} == {SECRET}
        assert client.get(URLS, params={"q": "s3cr3t"}, headers=service).json()["total"] == 3

        refreshed = client.post(f"{URLS}/{code}/refresh-preview", headers=service)
        assert refreshed.status_code == 200, refreshed.text

        assert client.delete(f"{URLS}/{code}", headers=creating).status_code == 204
        assert client.delete(f"{URLS}/acme-ana", headers=service).status_code == 204
        assert client.get(f"{URLS}/{code}", headers=service).status_code == 404

    def test_its_own_link_without_a_person_is_managed_too(self, client, db_session, world):
        made = _make_link(client, world["headers"]["manager"], url=SECRET)
        code = made.json()["short_code"]
        assert _link(db_session, code).created_by == world["manager"].id
        one = client.get(f"{URLS}/{code}", headers=world["headers"]["admin"])
        assert one.json()["original_url"] == MASK
        refused = client.delete(f"{URLS}/{code}", headers=world["headers"]["admin"])
        assert refused.json()["code"] == "managed_link_protected"
