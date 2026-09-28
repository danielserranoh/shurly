"""
Phase 3.14.3 — links and campaigns belong to the organization by default.

A link or campaign is the organization's unless its creator asks for a personal
one when making it:
- Everyone in the organization sees its links and campaigns, and their stats.
- A personal one is seen by its creator alone; to anyone else it doesn't exist (404).
- Its creator changes or deletes it; for the organization's, admins and owners too.
  Anyone else who can see it gets a 403.
- When someone leaves, an owner can move their personal links to the organization.
"""

from __future__ import annotations

import uuid

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.orm import Session

import server.app.urls as urls_module
from server.core.auth import create_access_token, hash_password
from server.core.models import URL, Campaign, OrganizationMember, OrgRole, User
from server.utils import organization as org_service
from server.utils.opengraph import OpenGraphMetadata

_PASSWORD_HASH = hash_password("secret123")


def _person(db: Session, email: str, role: OrgRole) -> User:
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=True)
    db.add(user)
    db.flush()
    organization = org_service.get_or_create_default_organization(db)
    db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=role))
    db.commit()
    db.refresh(user)
    return user


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


@pytest.fixture(autouse=True)
def no_og_fetch(monkeypatch):
    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


@pytest.fixture
def people(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "alice": _person(db_session, "alice@griddo.io", OrgRole.MEMBER),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


def _link(client, user: User, **extra) -> dict:
    body = {"url": "https://example.com/page", **extra}
    response = client.post("/api/v1/urls", json=body, headers=_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _campaign(client, user: User, **extra) -> dict:
    body = {
        "name": "Autumn",
        "original_url": "https://example.com/landing",
        "csv_data": "firstName,company\nAna,Acme\nLuis,Globex",
        **extra,
    }
    response = client.post("/api/v1/campaigns", json=body, headers=_headers(user))
    assert response.status_code == 201, response.text
    return response.json()


def _listed(client, user: User) -> set[str]:
    response = client.get("/api/v1/urls", headers=_headers(user))
    assert response.status_code == 200
    return {u["short_code"] for u in response.json()["urls"]}


class TestMakingLinks:
    def test_links_belong_to_the_organization_by_default(self, client, people):
        link = _link(client, people["alice"])

        assert link["visibility"] == "organization"
        assert link["created_by_email"] == "alice@griddo.io"

    def test_personal_only_on_request(self, client, people):
        assert _link(client, people["alice"], visibility="personal")["visibility"] == "personal"

    def test_custom_links_take_visibility_too(self, client, people):
        response = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com", "custom_code": "mine1", "visibility": "personal"},
            headers=_headers(people["alice"]),
        )

        assert response.status_code == 201
        assert response.json()["visibility"] == "personal"

    def test_campaigns_too(self, client, people):
        assert _campaign(client, people["alice"])["visibility"] == "organization"
        assert _campaign(client, people["alice"], visibility="personal")["visibility"] == "personal"

    def test_unknown_visibility_is_422(self, client, people):
        response = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com", "visibility": "everyone"},
            headers=_headers(people["alice"]),
        )

        assert response.status_code == 422


class TestSeeing:
    def test_organization_links_are_seen_by_everyone_in_it(self, client, people):
        code = _link(client, people["alice"])["short_code"]

        assert code in _listed(client, people["bob"])
        response = client.get(f"/api/v1/urls/{code}", headers=_headers(people["bob"]))
        assert response.status_code == 200
        assert response.json()["created_by_email"] == "alice@griddo.io"

    @pytest.mark.parametrize("viewer", ["bob", "admin", "owner"])
    def test_personal_links_exist_only_for_their_creator(self, client, people, viewer):
        code = _link(client, people["alice"], visibility="personal")["short_code"]

        assert code in _listed(client, people["alice"])
        assert code not in _listed(client, people[viewer])
        response = client.get(f"/api/v1/urls/{code}", headers=_headers(people[viewer]))
        assert response.status_code == 404

    def test_stats_follow_the_link(self, client, people):
        shared = _link(client, people["alice"])["short_code"]
        personal = _link(client, people["alice"], visibility="personal")["short_code"]
        bob = _headers(people["bob"])

        for kind in ("daily", "weekly", "geo"):
            assert (
                client.get(f"/api/v1/analytics/urls/{shared}/{kind}", headers=bob).status_code
                == 200
            )
            assert (
                client.get(f"/api/v1/analytics/urls/{personal}/{kind}", headers=bob).status_code
                == 404
            )
        csv = client.get(f"/api/v1/analytics/urls/{shared}/daily?format=csv", headers=bob)
        assert csv.status_code == 200 and csv.text.startswith("date,clicks")

    def test_overview_counts_what_you_can_see(self, client, people):
        _link(client, people["alice"])
        _link(client, people["alice"], visibility="personal")
        _link(client, people["bob"], visibility="personal")

        response = client.get("/api/v1/analytics/overview", headers=_headers(people["bob"]))

        assert response.status_code == 200
        assert response.json()["total_urls"] == 2  # alice's shared one + bob's own

    def test_campaigns_follow_the_same_rule(self, client, people):
        shared = _campaign(client, people["alice"])["id"]
        personal = _campaign(client, people["alice"], visibility="personal")["id"]
        bob = _headers(people["bob"])

        listed = {c["id"] for c in client.get("/api/v1/campaigns", headers=bob).json()["campaigns"]}
        assert shared in listed and personal not in listed
        assert client.get(f"/api/v1/campaigns/{shared}", headers=bob).status_code == 200
        assert client.get(f"/api/v1/campaigns/{shared}/export", headers=bob).status_code == 200
        assert (
            client.get(f"/api/v1/analytics/campaigns/{shared}/summary", headers=bob).status_code
            == 200
        )
        assert client.get(f"/api/v1/campaigns/{personal}", headers=bob).status_code == 404

    def test_campaign_links_follow_their_campaign(self, client, people, db_session):
        shared = _campaign(client, people["alice"])["id"]
        personal = _campaign(client, people["alice"], visibility="personal")["id"]

        def codes(campaign_id: str) -> set[str]:
            links = db_session.query(URL).filter(URL.campaign_id == uuid.UUID(campaign_id))
            return {link.short_code for link in links}

        listed = _listed(client, people["bob"])
        assert codes(shared) <= listed
        assert not codes(personal) & listed


def _changes(client, headers: dict, code: str) -> list:
    """Every way of changing a link, as (label, response)."""
    rule = {"conditions": [{"type": "device", "value": "ios"}], "target_url": "https://m.example"}
    return [
        ("edit", client.patch(f"/api/v1/urls/{code}", json={"title": "x"}, headers=headers)),
        ("tag", client.patch(f"/api/v1/urls/{code}/tags", json={"tag_ids": []}, headers=headers)),
        ("refresh", client.post(f"/api/v1/urls/{code}/refresh-preview", headers=headers)),
        ("rule", client.post(f"/api/v1/urls/{code}/rules", json=rule, headers=headers)),
        ("delete", client.delete(f"/api/v1/urls/{code}", headers=headers)),
    ]


class TestChanging:
    def test_members_cannot_change_someone_elses_organization_link(self, client, people):
        code = _link(client, people["alice"])["short_code"]

        refused = {
            label: r.status_code for label, r in _changes(client, _headers(people["bob"]), code)
        }

        assert refused == dict.fromkeys(refused, 403)
        assert code in _listed(client, people["alice"])

    @pytest.mark.parametrize("role", ["admin", "owner", "alice"])
    def test_admins_owners_and_the_creator_can(self, client, people, role):
        code = _link(client, people["alice"])["short_code"]

        done = {label: r.status_code for label, r in _changes(client, _headers(people[role]), code)}

        assert all(status < 300 for status in done.values()), done

    def test_nobody_else_touches_a_personal_link(self, client, people):
        code = _link(client, people["alice"], visibility="personal")["short_code"]

        for role in ("admin", "owner"):
            refused = {
                label: r.status_code for label, r in _changes(client, _headers(people[role]), code)
            }
            assert refused == dict.fromkeys(refused, 404)

    def test_bulk_tagging_skips_links_you_cannot_change(self, client, people):
        mine = _link(client, people["bob"])["short_code"]
        theirs = _link(client, people["alice"])["short_code"]

        response = client.post(
            "/api/v1/urls/bulk/tags",
            json={"short_codes": [mine, theirs], "tag_ids": []},
            headers=_headers(people["bob"]),
        )

        assert response.status_code == 200
        assert response.json()["updated"] == 1
        assert [f["short_code"] for f in response.json()["failed"]] == [theirs]

    def test_campaign_changes_need_the_role_too(self, client, people):
        campaign_id = _campaign(client, people["alice"])["id"]
        path = f"/api/v1/campaigns/{campaign_id}"

        bob = _headers(people["bob"])
        assert client.patch(f"{path}/tags", json={"tag_ids": []}, headers=bob).status_code == 403
        assert client.delete(path, headers=bob).status_code == 403
        assert client.delete(path, headers=_headers(people["admin"])).status_code == 204


class TestMcpTools:
    def test_curated_tools_follow_the_same_rules(self, db_session, people):
        from mcp_server import curated

        alice, bob, admin = people["alice"], people["bob"], people["admin"]
        created = curated.create_campaign_from_rows(
            db_session, alice, name="Rows", original_url="https://example.com", rows=[{"a": "1"}]
        )
        link = db_session.query(URL).filter(URL.campaign_id == uuid.UUID(created["id"])).one()
        code = link.short_code

        assert (
            curated.get_url_analytics_summary(db_session, bob, short_code=code)["short_code"]
            == code
        )
        with pytest.raises(PermissionError):
            curated.add_redirect_rule(
                db_session, bob, short_code=code, target_url="https://x.example", device="ios"
            )
        rule = curated.add_redirect_rule(
            db_session, admin, short_code=code, target_url="https://x.example", device="ios"
        )
        assert rule["target_url"] == "https://x.example"

    def test_campaign_from_rows_can_be_personal(self, db_session, people):
        from mcp_server import curated

        created = curated.create_campaign_from_rows(
            db_session,
            people["alice"],
            name="Mine",
            original_url="https://example.com",
            rows=[{"a": "1"}],
            visibility="personal",
        )

        assert created["visibility"] == "personal"
        assert db_session.get(Campaign, uuid.UUID(created["id"])).organization_id is None


class TestSomeoneLeaves:
    def _adopt(self, client, actor: User, leaver: User):
        return client.post(
            "/api/v1/organization/adopt-personal-links",
            json={"user_id": str(leaver.id)},
            headers=_headers(actor),
        )

    def test_owner_moves_their_personal_links_to_the_organization(self, client, people, capsys):
        code = _link(client, people["alice"], visibility="personal")["short_code"]
        campaign_id = _campaign(client, people["alice"], visibility="personal")["id"]
        client.delete(
            f"/api/v1/organization/members/{people['alice'].id}", headers=_headers(people["admin"])
        )
        capsys.readouterr()

        response = self._adopt(client, people["owner"], people["alice"])

        assert response.status_code == 200
        assert response.json() == {"links": 3, "campaigns": 1}  # the link + the campaign's two
        assert code in _listed(client, people["bob"])
        bob = _headers(people["bob"])
        assert client.get(f"/api/v1/campaigns/{campaign_id}", headers=bob).status_code == 200
        assert '"event": "org.links_adopted"' in capsys.readouterr().err

    def test_only_owners_do_it(self, client, people):
        _link(client, people["alice"], visibility="personal")
        client.delete(
            f"/api/v1/organization/members/{people['alice'].id}", headers=_headers(people["owner"])
        )

        assert self._adopt(client, people["admin"], people["alice"]).status_code == 403

    def test_not_while_they_are_still_here(self, client, people):
        _link(client, people["alice"], visibility="personal")

        assert self._adopt(client, people["owner"], people["alice"]).status_code == 409

    def test_unknown_person_is_404(self, client, people):
        response = client.post(
            "/api/v1/organization/adopt-personal-links",
            json={"user_id": str(uuid.uuid4())},
            headers=_headers(people["owner"]),
        )

        assert response.status_code == 404


_LEGACY_ROWS = (
    "INSERT INTO users (id, email, password_hash, api_key_scope, is_active, created_at)"
    " VALUES ('00000000-0000-0000-0000-00000000000b', 'a@griddo.io', 'x',"
    " 'FULL_ACCESS', true, now());"
    "INSERT INTO campaigns (id, name, original_url, csv_columns, created_by, created_at)"
    " VALUES ('00000000-0000-0000-0000-00000000000c', 'c', 'https://e.x', '[]',"
    " '00000000-0000-0000-0000-00000000000b', now());"
    "INSERT INTO urls (id, short_code, original_url, url_type, forward_parameters,"
    " crawlable, created_by, created_at, updated_at) VALUES"
    " ('00000000-0000-0000-0000-00000000000d', 'abc123', 'https://e.x', 'STANDARD',"
    " true, false, '00000000-0000-0000-0000-00000000000b', now(), now())"
)


def _migrate_legacy_rows(pg_engine, organization_first: bool) -> tuple:
    """Links and a campaign made at 0002, then upgraded: (organizations, urls, campaigns)."""
    from server.core.migrations import alembic_config

    config = alembic_config()
    with pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, "0002")
        if organization_first:
            conn.execute(
                text(
                    "INSERT INTO organizations (id, name, created_at)"
                    " VALUES ('00000000-0000-0000-0000-00000000000a', 'Griddo', now())"
                )
            )
        conn.execute(text(_LEGACY_ROWS))
        command.upgrade(config, "head")

        def ids(table: str) -> list[str]:
            column = "id" if table == "organizations" else "organization_id"
            return [row[0] for row in conn.execute(text(f"SELECT {column}::text FROM {table}"))]

        return ids("organizations"), ids("urls"), ids("campaigns")


def test_links_made_before_organizations_are_moved_into_one(pg_engine):
    """Migration 0003: existing links and campaigns become the organization's."""
    organizations, urls, campaigns = _migrate_legacy_rows(pg_engine, organization_first=True)

    assert organizations == ["00000000-0000-0000-0000-00000000000a"]
    assert urls == campaigns == organizations


def test_the_organization_is_made_when_0002_and_0003_run_in_one_boot(pg_engine):
    """The app makes the organization after migrating, so 0003 may find none yet."""
    organizations, urls, campaigns = _migrate_legacy_rows(pg_engine, organization_first=False)

    assert len(organizations) == 1
    assert urls == campaigns == organizations


def test_curated_summary_hides_personal_links_of_others(db_session, people):
    from mcp_server import curated

    link = URL(
        short_code="priv01",
        original_url="https://example.com",
        created_by=people["alice"].id,
        organization_id=None,
    )
    db_session.add(link)
    db_session.commit()

    with pytest.raises(LookupError):
        curated.get_url_analytics_summary(db_session, people["bob"], short_code="priv01")
