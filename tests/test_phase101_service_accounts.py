"""
Phase 10.1 — service accounts (`_pm/spec_service_accounts.md`).

Another system (Propuestas Griddo) makes links for the organization with its own token, naming
the person each link is for in `X-Shurly-On-Behalf-Of`:

- A service account is a user with `kind = 'service'`, a membership and a role. It never signs
  in, and lists of people leave it out.
- One token per account, `shsa_<prefix>_<secret>`, shown once and kept as a hash. Renewing keeps
  the old one for 24 hours; revoking ends it at once.
- The person named becomes the link's creator, the link is the organization's, and the link keeps
  which service account and token made it. The header grants nothing.
- The organization's owner manages them, signed in; admins read them.

Each item of the spec's "Acceptance" section is a test here (`TestAcceptance`), plus the rules
around them.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from server.core.auth import authenticate_user, create_access_token, hash_password, new_api_key
from server.core.models import (
    URL,
    OrganizationMember,
    OrgRole,
    ServiceToken,
    User,
    UserProfile,
)
from server.core.models.user import hash_api_key
from server.utils import organization as org_service

_PASSWORD_HASH = hash_password("secret123")
ON_BEHALF = "X-Shurly-On-Behalf-Of"
BASE = "/api/v1/service-accounts"


def _events(stderr: str, event: str) -> list[dict]:
    found = []
    for line in stderr.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and record.get("event") == event:
            found.append(record)
    return found


def _person(
    db: Session, email: str, role: OrgRole | None, first: str | None = None, last: str | None = None
) -> User:
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=True)
    db.add(user)
    db.flush()
    if role is not None:
        organization = org_service.get_or_create_default_organization(db)
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=role))
    if first or last:
        db.add(UserProfile(user_id=user.id, first_name=first, last_name=last))
    db.commit()
    db.refresh(user)
    return user


def _session(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _api_key(db: Session, user: User) -> dict:
    key = new_api_key()
    user.set_api_key(key)
    db.commit()
    return _bearer(key)


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER, "Olga", "Owner"),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "ana": _person(db_session, "ana.garcia@griddo.io", OrgRole.MEMBER, "Ana", "García"),
        "bob": _person(db_session, "bob@griddo.io", OrgRole.MEMBER),
    }


def _create_account(client, team, role="member", name="Propuestas Griddo") -> dict:
    response = client.post(
        BASE,
        json={
            "display_name": name,
            "description": "Hosts proposals and shortens their links",
            "responsible_user_id": str(team["ana"].id),
            "role": role,
        },
        headers=_session(team["owner"]),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _issue(client, team, account_id: str, **body) -> dict:
    response = client.post(
        f"{BASE}/{account_id}/token", json=body or None, headers=_session(team["owner"])
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def propuestas(client, team):
    """The service account, a `member`, and its token."""
    account = _create_account(client, team)
    issued = _issue(client, team, account["id"])
    return {"account": account, "token": issued["token"], "issued": issued}


def _make_link(client, headers, **body) -> object:
    return client.post(
        "/api/v1/urls", json={"url": "https://propuestas.griddo.io/p/1", **body}, headers=headers
    )


def _for_ana(propuestas) -> dict:
    return {**_bearer(propuestas["token"]), ON_BEHALF: "ana.garcia@griddo.io"}


class TestAcceptance:
    """`_pm/spec_service_accounts.md` § Acceptance, one test per item."""

    def test_the_owner_makes_an_account_and_its_token_shown_once(self, client, team):
        account = _create_account(client, team)
        assert account["display_name"] == "Propuestas Griddo"
        assert account["role"] == "member"
        assert account["responsible"]["user_id"] == str(team["ana"].id)
        assert account["responsible"]["first_name"] == "Ana"
        assert account["token"] is None

        issued = _issue(client, team, account["id"])
        token = issued["token"]
        assert token.startswith("shsa_")
        start, prefix, secret = token.split("_", 2)
        assert start == "shsa" and len(prefix) == 8 and len(secret) >= 43  # 32 bytes
        assert issued["prefix"] == f"shsa_{prefix}"
        assert issued["renewed"] is False

        # Afterwards, only the prefix: never the token, nor its hash.
        listed = client.get(BASE, headers=_session(team["owner"]))
        assert listed.status_code == 200
        [row] = listed.json()
        assert row["token"]["prefix"] == f"shsa_{prefix}"
        assert secret not in listed.text and token not in listed.text
        assert hash_api_key(token) not in listed.text

    def test_an_admin_reads_the_accounts_but_changes_nothing(self, client, team, propuestas):
        admin = _session(team["admin"])
        listed = client.get(BASE, headers=admin)
        assert listed.status_code == 200
        assert [row["display_name"] for row in listed.json()] == ["Propuestas Griddo"]

        account_id = propuestas["account"]["id"]
        refused = [
            client.post(
                BASE,
                json={"display_name": "X", "responsible_user_id": str(team["ana"].id)},
                headers=admin,
            ),
            client.patch(f"{BASE}/{account_id}", json={"role": "admin"}, headers=admin),
            client.delete(f"{BASE}/{account_id}", headers=admin),
            client.post(f"{BASE}/{account_id}/token", headers=admin),
            client.delete(f"{BASE}/{account_id}/token", headers=admin),
        ]
        assert [r.status_code for r in refused] == [403] * 5

    def test_a_member_sees_nothing(self, client, team, propuestas):
        member = _session(team["bob"])
        assert client.get(BASE, headers=member).status_code == 403
        assert (
            client.get(f"{BASE}/{propuestas['account']['id']}/links", headers=member).status_code
            == 403
        )

    def test_a_link_for_ana(self, client, team, propuestas, db_session):
        response = _make_link(client, _for_ana(propuestas))
        assert response.status_code == 201, response.text
        link = response.json()

        assert link["created_by_email"] == "ana.garcia@griddo.io"
        assert (link["created_by_first_name"], link["created_by_last_name"]) == ("Ana", "García")
        assert link["via_service_account"] == {
            "id": propuestas["account"]["id"],
            "display_name": "Propuestas Griddo",
        }
        assert link["visibility"] == "organization"
        # Never the token, nor the token's reference.
        assert propuestas["token"] not in response.text
        assert propuestas["issued"]["id"] not in response.text
        assert "via_token" not in link

        row = db_session.query(URL).filter(URL.short_code == link["short_code"]).one()
        assert row.created_by == team["ana"].id
        assert str(row.via_service_account_id) == propuestas["account"]["id"]
        assert str(row.via_token_id) == propuestas["issued"]["id"]
        assert row.organization_id is not None

        # Ana sees it as hers. Since 10.3 it's managed by Propuestas (server/utils/managed.py):
        # she changes its tags, the one thing people change on it, but not its title or
        # anything else, which Propuestas changes. The test's point stays: what she may do on
        # the link made for her, as its creator.
        mine = client.get(f"/api/v1/urls/{link['short_code']}", headers=_session(team["ana"]))
        assert mine.json()["via_service_account"]["display_name"] == "Propuestas Griddo"
        assert mine.json()["managed_by"]["display_name"] == "Propuestas Griddo"
        changed = client.patch(
            f"/api/v1/urls/{link['short_code']}",
            json={"title": "Mine"},
            headers=_session(team["ana"]),
        )
        assert changed.status_code == 403
        assert changed.json()["code"] == "managed_link_protected"
        tag = client.post("/api/v1/tags", json={"name": "Ana's"}, headers=_session(team["ana"]))
        assert tag.status_code == 201, tag.text
        tagged = client.patch(
            f"/api/v1/urls/{link['short_code']}/tags",
            json={"tag_ids": [tag.json()["id"]]},
            headers=_session(team["ana"]),
        )
        assert tagged.status_code == 200, tagged.text

    def test_an_email_that_isnt_a_user_is_a_422_and_no_link(self, client, propuestas, db_session):
        before = db_session.query(URL).count()
        response = _make_link(
            client, {**_bearer(propuestas["token"]), ON_BEHALF: "nobody@griddo.io"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "on_behalf_of_unknown"
        assert isinstance(response.json()["detail"], str)
        assert db_session.query(URL).count() == before

    def test_a_persons_api_key_with_the_header_is_a_403(self, client, team, db_session):
        headers = {**_api_key(db_session, team["bob"]), ON_BEHALF: "ana.garcia@griddo.io"}
        response = _make_link(client, headers)
        assert response.status_code == 403
        assert response.json()["code"] == "on_behalf_of_not_allowed"
        assert isinstance(response.json()["detail"], str)
        # A session too.
        session = {**_session(team["bob"]), ON_BEHALF: "ana.garcia@griddo.io"}
        assert _make_link(client, session).json()["code"] == "on_behalf_of_not_allowed"

    def test_a_member_service_changes_and_deletes_its_links_but_not_anothers(
        self, client, team, propuestas
    ):
        service = _bearer(propuestas["token"])
        made = _make_link(client, _for_ana(propuestas)).json()

        patched = client.patch(
            f"/api/v1/urls/{made['short_code']}",
            json={"valid_until": "2030-01-01T00:00:00Z"},
            headers=service,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["valid_until"].startswith("2030-01-01")

        bobs = _make_link(client, _session(team["bob"])).json()
        refused = client.patch(
            f"/api/v1/urls/{bobs['short_code']}", json={"title": "Taken"}, headers=service
        )
        assert refused.status_code == 403
        assert (
            client.delete(f"/api/v1/urls/{bobs['short_code']}", headers=service).status_code == 403
        )

        deleted = client.delete(f"/api/v1/urls/{made['short_code']}", headers=service)
        assert deleted.status_code == 204

    def test_renewing_overlaps_24_hours_and_revoking_ends_it(
        self, client, team, propuestas, db_session
    ):
        account_id = propuestas["account"]["id"]
        old = propuestas["token"]
        renewed = _issue(client, team, account_id)
        assert renewed["renewed"] is True
        new = renewed["token"]
        assert new != old

        me = "/api/v1/auth/me"
        assert client.get(me, headers=_bearer(old)).status_code == 200
        assert client.get(me, headers=_bearer(new)).status_code == 200

        listed = client.get(BASE, headers=_session(team["owner"])).json()[0]
        assert listed["token"]["prefix"] == renewed["prefix"]
        assert listed["previous_token"]["prefix"] == propuestas["issued"]["prefix"]
        assert listed["previous_token"]["valid_until"] is not None

        # 23 hours and 59 minutes on: still in.
        old_row = (
            db_session.query(ServiceToken).filter_by(id=uuid.UUID(propuestas["issued"]["id"])).one()
        )
        old_row.replaced_at = datetime.utcnow() - timedelta(hours=23, minutes=59)
        db_session.commit()
        assert client.get(me, headers=_bearer(old)).status_code == 200
        # Past 24 hours: out, as an unknown token is.
        old_row.replaced_at = datetime.utcnow() - timedelta(hours=24, seconds=1)
        db_session.commit()
        assert client.get(me, headers=_bearer(old)).status_code == 401
        assert client.get(me, headers=_bearer(new)).status_code == 200

        # "Revoke the old one now" ends it at once.
        newer = _issue(client, team, account_id)["token"]
        assert client.get(me, headers=_bearer(new)).status_code == 200
        ended = client.delete(
            f"{BASE}/{account_id}/token?old_only=true", headers=_session(team["owner"])
        )
        assert ended.status_code == 204
        assert client.get(me, headers=_bearer(new)).status_code == 401
        assert client.get(me, headers=_bearer(newer)).status_code == 200

        # Revoking: the next request is a 401.
        assert (
            client.delete(f"{BASE}/{account_id}/token", headers=_session(team["owner"])).status_code
            == 204
        )
        assert client.get(me, headers=_bearer(newer)).status_code == 401

    def test_the_links_a_token_created(self, client, team, propuestas):
        account_id = propuestas["account"]["id"]
        first = _make_link(client, _for_ana(propuestas)).json()
        second_token = _issue(client, team, account_id)
        second = _make_link(
            client, {**_bearer(second_token["token"]), ON_BEHALF: "bob@griddo.io"}
        ).json()
        _make_link(client, _session(team["bob"]))  # a person's, with no service

        owner = _session(team["owner"])
        everything = client.get(f"{BASE}/{account_id}/links", headers=owner).json()
        assert {url["short_code"] for url in everything["urls"]} == {
            first["short_code"],
            second["short_code"],
        }
        assert everything["total"] == 2

        leaked = client.get(
            f"{BASE}/{account_id}/links?token_id={propuestas['issued']['id']}", headers=owner
        ).json()
        assert [url["short_code"] for url in leaked["urls"]] == [first["short_code"]]
        assert leaked["total"] == 1
        # An admin reads it too.
        admin = client.get(f"{BASE}/{account_id}/links", headers=_session(team["admin"]))
        assert admin.status_code == 200

    def test_a_service_account_cant_sign_in_make_a_key_set_a_password_or_manage(
        self, client, team, propuestas, db_session
    ):
        service = _bearer(propuestas["token"])
        account = db_session.get(User, uuid.UUID(propuestas["account"]["id"]))

        # No password login, even if one were set by hand.
        account.password_hash = _PASSWORD_HASH
        db_session.commit()
        login = client.post(
            "/api/v1/auth/login", json={"email": account.email, "password": "secret123"}
        )
        assert login.status_code == 422  # a `.invalid` address isn't even an email to log in with
        assert authenticate_user(db_session, account.email, "secret123") is None
        # No session, even with a JWT for its address.
        jwt = _bearer(create_access_token(data={"sub": account.email}))
        assert client.get("/api/v1/auth/me", headers=jwt).status_code == 401

        for method, path, body in [
            ("post", "/api/v1/auth/api-key/generate", None),
            ("put", "/api/v1/auth/password", {"new_password": "longenough1"}),
            ("delete", "/api/v1/auth/password", None),
            (
                "post",
                "/api/v1/auth/change-password",
                {"current_password": "secret123", "new_password": "longenough1"},
            ),
            ("get", BASE, None),
            ("post", BASE, {"display_name": "Y", "responsible_user_id": str(team["ana"].id)}),
            ("post", f"{BASE}/{account.id}/token", None),
            ("delete", f"{BASE}/{account.id}/token", None),
        ]:
            response = client.request(method, path, json=body, headers=service)
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["code"] == "service_account_not_allowed", (method, path)
        db_session.refresh(account)
        assert account.api_key_hash is None

    def test_peoples_keys_and_sessions_work_as_before(self, client, team, db_session):
        key = _api_key(db_session, team["bob"])
        assert client.get("/api/v1/auth/me", headers=key).json()["email"] == "bob@griddo.io"
        made = _make_link(client, key)
        assert made.status_code == 201
        assert made.json()["via_service_account"] is None
        assert made.json()["created_by_email"] == "bob@griddo.io"
        by_session = _make_link(client, _session(team["ana"]), visibility="personal")
        assert by_session.status_code == 201
        assert by_session.json()["via_service_account"] is None
        assert by_session.json()["visibility"] == "personal"
        # An API key still can't manage passwords, with the same answer as before.
        refused = client.post("/api/v1/auth/api-key/generate", headers=key)
        assert refused.status_code == 403
        assert "code" not in refused.json()
        assert client.get("/api/v1/auth/me", headers=_bearer("shurly_nope")).status_code == 401


class TestTokens:
    def test_the_token_is_kept_as_a_hash(self, propuestas, db_session):
        row = db_session.query(ServiceToken).one()
        assert row.token_hash == hash_api_key(propuestas["token"])
        assert propuestas["token"] not in {row.prefix, row.token_hash}

    @pytest.mark.parametrize("variant", ["unknown", "revoked", "expired", "inactive"])
    def test_every_refused_token_is_the_same_401(
        self, client, team, propuestas, db_session, variant
    ):
        token = propuestas["token"]
        row = db_session.query(ServiceToken).one()
        if variant == "unknown":
            token = token[:-4] + "AAAA"
        elif variant == "revoked":
            row.revoked_at = datetime.utcnow()
        elif variant == "expired":
            row.expires_at = datetime.utcnow() - timedelta(seconds=1)
        else:
            db_session.get(User, row.service_account_id).is_active = False
        db_session.commit()
        response = client.get("/api/v1/auth/me", headers=_bearer(token))
        assert response.status_code == 401
        assert response.json() == {"detail": "Could not validate credentials"}

    def test_an_expiry_in_the_future(self, client, team):
        account = _create_account(client, team)
        later = (datetime.utcnow() + timedelta(days=30)).replace(
            microsecond=0
        ).isoformat() + "+00:00"
        issued = _issue(client, team, account["id"], expires_at=later)
        assert issued["expires_at"].startswith(later[:19])
        past = client.post(
            f"{BASE}/{account['id']}/token",
            json={"expires_at": "2020-01-01T00:00:00+00:00"},
            headers=_session(team["owner"]),
        )
        assert past.status_code == 422

    def test_last_use_is_written_at_most_once_a_minute(self, client, propuestas, db_session):
        row = db_session.query(ServiceToken).one()
        assert row.last_used_at is None
        client.get("/api/v1/auth/me", headers=_bearer(propuestas["token"]))
        db_session.refresh(row)
        first = row.last_used_at
        assert first is not None
        client.get("/api/v1/auth/me", headers=_bearer(propuestas["token"]))
        db_session.refresh(row)
        assert row.last_used_at == first
        row.last_used_at = first - timedelta(minutes=2)
        db_session.commit()
        client.get("/api/v1/auth/me", headers=_bearer(propuestas["token"]))
        db_session.refresh(row)
        assert row.last_used_at > first - timedelta(minutes=2)

    def test_one_token_in_its_overlap_at_a_time(self, client, team, propuestas, db_session):
        account_id = propuestas["account"]["id"]
        second = _issue(client, team, account_id)["token"]
        third = _issue(client, team, account_id)["token"]
        me = "/api/v1/auth/me"
        assert client.get(me, headers=_bearer(propuestas["token"])).status_code == 401
        assert client.get(me, headers=_bearer(second)).status_code == 200
        assert client.get(me, headers=_bearer(third)).status_code == 200

    def test_the_service_is_the_current_user(self, client, propuestas):
        me = client.get("/api/v1/auth/me", headers=_bearer(propuestas["token"])).json()
        assert me["id"] == propuestas["account"]["id"]
        assert me["email"].endswith("@service.invalid")


class TestActingOnBehalf:
    def test_without_the_header_the_service_is_the_creator(self, client, propuestas, db_session):
        link = _make_link(client, _bearer(propuestas["token"])).json()
        assert link["via_service_account"]["id"] == propuestas["account"]["id"]
        row = db_session.query(URL).filter(URL.short_code == link["short_code"]).one()
        assert str(row.created_by) == propuestas["account"]["id"]
        assert row.organization_id is not None

    def test_its_links_are_never_personal(self, client, propuestas):
        link = _make_link(client, _for_ana(propuestas), visibility="personal").json()
        assert link["visibility"] == "organization"
        own = _make_link(client, _bearer(propuestas["token"]), visibility="personal").json()
        assert own["visibility"] == "organization"

    def test_custom_links_too(self, client, propuestas):
        response = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://propuestas.griddo.io/p/2", "custom_code": "prop-ana"},
            headers=_for_ana(propuestas),
        )
        assert response.status_code == 201, response.text
        assert response.json()["created_by_email"] == "ana.garcia@griddo.io"
        assert response.json()["via_service_account"]["display_name"] == "Propuestas Griddo"
        unknown = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://propuestas.griddo.io/p/2", "custom_code": "prop-x"},
            headers={**_bearer(propuestas["token"]), ON_BEHALF: "x@griddo.io"},
        )
        assert unknown.json()["code"] == "on_behalf_of_unknown"

    def test_the_email_is_matched_without_case(self, client, propuestas):
        headers = {**_bearer(propuestas["token"]), ON_BEHALF: " Ana.Garcia@Griddo.io "}
        assert _make_link(client, headers).json()["created_by_email"] == "ana.garcia@griddo.io"

    def test_a_removed_person_or_another_service_is_unknown(
        self, client, team, propuestas, db_session
    ):
        team["bob"].is_active = False
        db_session.commit()
        bob = {**_bearer(propuestas["token"]), ON_BEHALF: "bob@griddo.io"}
        assert _make_link(client, bob).json()["code"] == "on_behalf_of_unknown"
        other = _create_account(client, team, name="Other")
        service_email = db_session.get(User, uuid.UUID(other["id"])).email
        as_service = {**_bearer(propuestas["token"]), ON_BEHALF: service_email}
        assert _make_link(client, as_service).json()["code"] == "on_behalf_of_unknown"

    def test_someone_outside_the_organization_is_unknown(self, client, propuestas, db_session):
        _person(db_session, "stranger@example.com", None)
        headers = {**_bearer(propuestas["token"]), ON_BEHALF: "stranger@example.com"}
        assert _make_link(client, headers).json()["code"] == "on_behalf_of_unknown"

    def test_acting_for_an_owner_grants_nothing(self, client, team, propuestas):
        bobs = _make_link(client, _session(team["bob"])).json()
        as_owner = {**_bearer(propuestas["token"]), ON_BEHALF: "owner@griddo.io"}
        refused = client.patch(
            f"/api/v1/urls/{bobs['short_code']}", json={"title": "x"}, headers=as_owner
        )
        assert refused.status_code == 403
        assert (
            client.delete(f"/api/v1/urls/{bobs['short_code']}", headers=as_owner).status_code == 403
        )

    def test_an_admin_service_changes_the_organizations_links(self, client, team):
        account = _create_account(client, team, role="admin", name="Ops bot")
        token = _issue(client, team, account["id"])["token"]
        bobs = _make_link(client, _session(team["bob"])).json()
        changed = client.patch(
            f"/api/v1/urls/{bobs['short_code']}", json={"title": "Fixed"}, headers=_bearer(token)
        )
        assert changed.status_code == 200
        # Not someone's personal one: it doesn't see it.
        personal = _make_link(client, _session(team["bob"]), visibility="personal").json()
        hidden = client.get(f"/api/v1/urls/{personal['short_code']}", headers=_bearer(token))
        assert hidden.status_code == 404

    def test_a_person_sending_the_header_on_a_change_is_a_403(self, client, team):
        bobs = _make_link(client, _session(team["bob"])).json()
        headers = {**_session(team["bob"]), ON_BEHALF: "ana.garcia@griddo.io"}
        response = client.patch(
            f"/api/v1/urls/{bobs['short_code']}", json={"title": "x"}, headers=headers
        )
        assert response.status_code == 403
        assert response.json()["code"] == "on_behalf_of_not_allowed"

    def test_campaigns_follow_the_same_rule(self, client, team, propuestas, db_session):
        body = {
            "name": "Proposals",
            "original_url": "https://propuestas.griddo.io/p/3",
            "csv_data": "firstName\nLuis\nMar",
        }
        made = client.post("/api/v1/campaigns", json=body, headers=_for_ana(propuestas))
        assert made.status_code == 201, made.text
        assert made.json()["created_by_email"] == "ana.garcia@griddo.io"
        urls = db_session.query(URL).filter(URL.campaign_id == uuid.UUID(made.json()["id"])).all()
        assert len(urls) == 2
        assert all(url.created_by == team["ana"].id for url in urls)
        assert all(str(url.via_service_account_id) == propuestas["account"]["id"] for url in urls)
        assert all(str(url.via_token_id) == propuestas["issued"]["id"] for url in urls)
        unknown = client.post(
            "/api/v1/campaigns",
            json=body,
            headers={**_bearer(propuestas["token"]), ON_BEHALF: "x@y.z"},
        )
        assert unknown.status_code == 422 and unknown.json()["code"] == "on_behalf_of_unknown"
        refused = client.post(
            "/api/v1/campaigns",
            json=body,
            headers={**_session(team["bob"]), ON_BEHALF: "ana.garcia@griddo.io"},
        )
        assert refused.json()["code"] == "on_behalf_of_not_allowed"

    def test_the_links_list_filters_by_service_account(self, client, team, propuestas):
        mine = _make_link(client, _for_ana(propuestas)).json()
        _make_link(client, _session(team["bob"]))
        listed = client.get(
            f"/api/v1/urls?via_service_account={propuestas['account']['id']}",
            headers=_session(team["bob"]),
        ).json()
        assert [url["short_code"] for url in listed["urls"]] == [mine["short_code"]]
        assert listed["total"] == 1
        everything = client.get("/api/v1/urls", headers=_session(team["bob"])).json()
        assert everything["total"] == 2


class TestManagement:
    def test_api_keys_cant_manage_them(self, client, team, db_session):
        key = _api_key(db_session, team["owner"])
        assert client.get(BASE, headers=key).status_code == 403
        made = client.post(
            BASE,
            json={"display_name": "X", "responsible_user_id": str(team["ana"].id)},
            headers=key,
        )
        assert made.status_code == 403

    def test_the_person_responsible_must_be_in_the_organization(self, client, team, db_session):
        stranger = _person(db_session, "stranger@example.com", None)
        response = client.post(
            BASE,
            json={"display_name": "X", "responsible_user_id": str(stranger.id)},
            headers=_session(team["owner"]),
        )
        assert response.status_code == 422

    def test_a_service_is_a_member_or_an_admin(self, client, team):
        response = client.post(
            BASE,
            json={"display_name": "X", "responsible_user_id": str(team["ana"].id), "role": "owner"},
            headers=_session(team["owner"]),
        )
        assert response.status_code == 422

    def test_editing(self, client, team, propuestas, db_session):
        account_id = propuestas["account"]["id"]
        response = client.patch(
            f"{BASE}/{account_id}",
            json={
                "display_name": "Propuestas",
                "description": "Proposals",
                "responsible_user_id": str(team["bob"].id),
                "role": "admin",
            },
            headers=_session(team["owner"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["display_name"], body["description"], body["role"]) == (
            "Propuestas",
            "Proposals",
            "admin",
        )
        assert body["responsible"]["user_id"] == str(team["bob"].id)
        assert body["token"]["prefix"] == propuestas["issued"]["prefix"]
        assert (
            client.patch(
                f"{BASE}/{uuid.uuid4()}", json={"role": "admin"}, headers=_session(team["owner"])
            ).status_code
            == 404
        )

    def test_removing_revokes_its_tokens_and_keeps_its_links(
        self, client, team, propuestas, db_session
    ):
        link = _make_link(client, _for_ana(propuestas)).json()
        account_id = propuestas["account"]["id"]
        assert (
            client.delete(f"{BASE}/{account_id}", headers=_session(team["owner"])).status_code
            == 204
        )
        assert (
            client.get("/api/v1/auth/me", headers=_bearer(propuestas["token"])).status_code == 401
        )
        assert client.get(BASE, headers=_session(team["owner"])).json() == []
        kept = client.get(
            f"/api/v1/urls/{link['short_code']}", headers=_session(team["ana"])
        ).json()
        assert kept["via_service_account"]["display_name"] == "Propuestas Griddo"
        assert db_session.query(ServiceToken).filter(ServiceToken.revoked_at.is_(None)).count() == 0
        assert (
            client.delete(f"{BASE}/{account_id}", headers=_session(team["owner"])).status_code
            == 404
        )

    def test_events_never_carry_a_secret_hash_or_email(self, client, team, capsys):
        capsys.readouterr()
        account = _create_account(client, team)
        issued = _issue(client, team, account["id"])
        renewed = _issue(client, team, account["id"])
        headers = {**_bearer(renewed["token"]), ON_BEHALF: "ana.garcia@griddo.io"}
        link = _make_link(client, headers).json()
        client.patch(f"/api/v1/urls/{link['short_code']}", json={"title": "t"}, headers=headers)
        client.delete(f"/api/v1/urls/{link['short_code']}", headers=headers)
        client.patch(
            f"{BASE}/{account['id']}", json={"role": "admin"}, headers=_session(team["owner"])
        )
        client.delete(
            f"{BASE}/{account['id']}/token?old_only=true", headers=_session(team["owner"])
        )
        client.delete(f"{BASE}/{account['id']}", headers=_session(team["owner"]))
        err = capsys.readouterr().err

        for event in (
            "service_account.created",
            "service_token.created",
            "service_token.renewed",
            "url.created",
            "url.updated",
            "url.deleted",
            "service_account.updated",
            "service_token.revoked",
            "service_account.removed",
        ):
            assert _events(err, event), event
        [created] = _events(err, "url.created")
        assert created["service_account_id"] == account["id"]
        assert created["token_id"] == renewed["id"]
        assert created["on_behalf_of"] == str(team["ana"].id)
        assert created["url_id"] == link["id"]
        [deleted] = _events(err, "url.deleted")
        assert deleted["url_id"] == link["id"] and deleted["on_behalf_of"] == str(team["ana"].id)
        [renewal] = _events(err, "service_token.renewed")
        assert renewal["replaced_token_id"] == issued["id"]
        for secret in (issued["token"], renewed["token"], hash_api_key(issued["token"])):
            assert secret not in err
        assert "ana.garcia@griddo.io" not in err
        assert issued["token"].split("_", 2)[2] not in err

    def test_a_persons_links_log_no_url_event(self, client, team, capsys):
        capsys.readouterr()
        _make_link(client, _session(team["bob"]))
        assert _events(capsys.readouterr().err, "url.created") == []


class TestNotAPerson:
    def test_the_members_list_leaves_it_out(self, client, team, propuestas):
        members = client.get("/api/v1/organization/members", headers=_session(team["owner"])).json()
        assert propuestas["account"]["id"] not in {m["user_id"] for m in members}
        assert len(members) == 4

    def test_the_member_routes_dont_reach_it(self, client, team, propuestas):
        owner = _session(team["owner"])
        account_id = propuestas["account"]["id"]
        assert (
            client.patch(
                f"/api/v1/organization/members/{account_id}", json={"role": "admin"}, headers=owner
            ).status_code
            == 404
        )
        assert (
            client.delete(f"/api/v1/organization/members/{account_id}", headers=owner).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/organization/transfer-ownership",
                json={"user_id": account_id},
                headers=owner,
            ).status_code
            == 404
        )

    def test_removed_people_and_adoption_leave_it_out(self, client, team, propuestas, monkeypatch):
        from server.core.config import settings

        monkeypatch.setattr(settings, "organization_domain", "")  # any address counts
        owner = _session(team["owner"])
        client.delete(f"{BASE}/{propuestas['account']['id']}", headers=owner)
        removed = client.get("/api/v1/organization/removed-members", headers=owner).json()
        assert propuestas["account"]["id"] not in {p["user_id"] for p in removed}
        adopt = client.post(
            "/api/v1/organization/adopt-personal-links",
            json={"user_id": propuestas["account"]["id"]},
            headers=owner,
        )
        assert adopt.status_code == 404

    def test_an_admin_service_doesnt_change_the_organization(self, client, team, db_session):
        account = _create_account(client, team, role="admin", name="Ops bot")
        service = _bearer(_issue(client, team, account["id"])["token"])
        for method, path, body in [
            ("patch", f"/api/v1/organization/members/{team['bob'].id}", {"role": "admin"}),
            ("delete", f"/api/v1/organization/members/{team['bob'].id}", None),
            ("get", "/api/v1/organization/removed-members", None),
            ("delete", "/api/v1/organization/logo", None),
            ("get", "/api/v1/waitlist", None),
        ]:
            response = client.request(method, path, json=body, headers=service)
            assert response.status_code == 403, (method, path, response.text)
        db_session.refresh(team["bob"])
        assert team["bob"].is_active

    def test_the_last_owner_rule_counts_people_only(self, db_session, team):
        organization = org_service.get_or_create_default_organization(db_session)
        service = User(
            email="bot@service.invalid", kind="service", display_name="Bot", is_active=True
        )
        db_session.add(service)
        db_session.flush()
        # Even a service row with the owner role (never made by the API) doesn't count.
        db_session.add(
            OrganizationMember(
                organization_id=organization.id, user_id=service.id, role=OrgRole.OWNER
            )
        )
        db_session.commit()
        with pytest.raises(org_service.LastOwner):
            org_service.change_role(db_session, team["owner"], team["owner"].id, OrgRole.ADMIN)

    def test_startup_doesnt_make_it_a_member_or_the_bootstrap_owner(self, db_session, monkeypatch):
        from server.core.config import settings

        service = User(
            email="boot@service.invalid", kind="service", display_name="Boot", is_active=True
        )
        db_session.add(service)
        db_session.commit()
        monkeypatch.setattr(settings, "bootstrap_owner_email", "boot@service.invalid")
        monkeypatch.setattr(settings, "organization_domain", "")
        org_service.ensure_memberships(db_session)
        db_session.commit()
        assert org_service.get_membership(db_session, service) is None

    def test_google_sign_in_refuses_it(self, db_session, propuestas):
        from server.core.models import UserIdentity
        from server.utils.google_oidc import GoogleAccount, GoogleSignInError
        from server.utils.google_sign_in import (
            issue_login_code,
            redeem_login_code,
            sign_in_with_google,
        )

        account = db_session.get(User, uuid.UUID(propuestas["account"]["id"]))
        with pytest.raises(GoogleSignInError) as refused:
            sign_in_with_google(db_session, GoogleAccount(subject="g-1", email=account.email))
        assert refused.value.reason == "service_account"
        # Linked by hand, it's still refused.
        db_session.add(
            UserIdentity(user_id=account.id, provider="google", subject="g-2", email="x@griddo.io")
        )
        db_session.commit()
        with pytest.raises(GoogleSignInError):
            sign_in_with_google(db_session, GoogleAccount(subject="g-2", email="x@griddo.io"))
        code = issue_login_code(db_session, account)
        assert redeem_login_code(db_session, code) is None


class TestMcp:
    """The MCP is for people: it takes no service token, and never says whom a link is for."""

    def test_the_mcp_refuses_a_service_token(self, propuestas):
        pytest.importorskip("fastmcp")
        import asyncio

        from mcp_server.auth import ShurlyTokenVerifier
        from tests.conftest import TestingSessionLocal

        verifier = ShurlyTokenVerifier(session_factory=TestingSessionLocal)
        assert asyncio.run(verifier.verify_token(propuestas["token"])) is None

    def test_the_mcp_google_sign_in_refuses_it(self, db_session, propuestas):
        pytest.importorskip("fastmcp")
        from mcp_server.google_oauth import ShurlyGoogleProvider
        from server.core.models import UserIdentity
        from tests.conftest import TestingSessionLocal

        account_id = uuid.UUID(propuestas["account"]["id"])
        db_session.add(
            UserIdentity(user_id=account_id, provider="google", subject="g-9", email="z@griddo.io")
        )
        db_session.commit()

        class Probe:
            _session_factory = TestingSessionLocal

        assert ShurlyGoogleProvider._active_account(Probe(), "g-9") is None

    def test_no_tool_takes_the_header_or_manages_service_accounts(self):
        pytest.importorskip("fastmcp")
        import asyncio

        from mcp_server.server import _build_mcp_server

        tools = asyncio.run(_build_mcp_server().list_tools())
        for tool in tools:
            schema = json.dumps(tool.parameters).lower()
            assert "on-behalf" not in schema and "on_behalf" not in schema, tool.name
            assert "service_account" not in tool.name and "service-account" not in tool.name, (
                tool.name
            )

    def test_the_header_is_never_forwarded(self):
        pytest.importorskip("fastmcp")
        import httpx2

        from mcp_server.auth import forward_bearer_auth

        request = httpx2.Request(
            "POST", "http://test/api/v1/urls", headers={ON_BEHALF: "ana.garcia@griddo.io"}
        )
        assert ON_BEHALF not in forward_bearer_auth(request).headers

    def test_the_api_schema_doesnt_declare_the_header(self):
        from main import app

        operation = app.openapi()["paths"]["/api/v1/urls"]["post"]
        assert all(p.get("in") != "header" for p in operation.get("parameters", []))


class TestMigration:
    """0017 is add-only: every account so far is a person, and the previous release keeps working."""

    def test_existing_accounts_become_people_and_old_inserts_still_work(self, pg_engine):
        from alembic import command
        from sqlalchemy import inspect, text

        from server.core.migrations import alembic_config

        insert = text(
            "INSERT INTO users (id, email, password_hash, api_key_scope, is_active, created_at)"
            " VALUES (gen_random_uuid(), :email, 'x', 'FULL_ACCESS', true, now())"
        )
        config = alembic_config()
        with pg_engine.begin() as conn:
            config.attributes["connection"] = conn
            command.upgrade(config, "0016")
            conn.execute(insert, {"email": "before@griddo.io"})
            command.upgrade(config, "0017")
            # The previous release's insert names none of the new columns.
            conn.execute(insert, {"email": "during@griddo.io"})

        with pg_engine.connect() as conn:
            kinds = dict(conn.execute(text("SELECT email, kind FROM users")).all())
            columns = {c["name"] for c in inspect(conn).get_columns("urls")}
        assert kinds == {"before@griddo.io": "person", "during@griddo.io": "person"}
        assert {"via_service_account_id", "via_token_id"} <= columns

        with pg_engine.begin() as conn:
            config.attributes["connection"] = conn
            command.downgrade(config, "0016")
            command.upgrade(config, "0017")
