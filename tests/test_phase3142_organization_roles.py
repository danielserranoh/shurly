"""
Phase 3.14.2 — the organization, its members and their roles.

One organization at launch ("Griddo"). Every account belongs to it as owner,
admin or member:
- Owners change the roles of admins and members, make other owners, and step
  down or hand the role over. They never change another owner's role.
- Admins remove members; they change no roles.
- Nobody changes the role of someone whose role is equal to or above theirs.
- There is always at least one owner: the last one can't step down or be removed.
- The first owner comes from configuration (BOOTSTRAP_OWNER_EMAIL), not from
  whoever signs up first.
"""

from __future__ import annotations

import json
import threading

import pytest
from sqlalchemy.orm import Session, sessionmaker

from server.core.auth import create_access_token, hash_password
from server.core.config import settings
from server.core.models import Organization, OrganizationMember, OrgRole, User
from server.utils import organization as org_service


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


# bcrypt is slow on purpose; hash once for every user these tests create.
_PASSWORD_HASH = hash_password("secret123")


def _person(db: Session, email: str, role: OrgRole | None) -> User:
    """A user; with a role, also a member of the default organization."""
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=True)
    db.add(user)
    db.flush()
    if role is not None:
        organization = org_service.get_or_create_default_organization(db)
        db.add(OrganizationMember(organization_id=organization.id, user_id=user.id, role=role))
    db.commit()
    db.refresh(user)
    return user


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


def _role(db: Session, user: User) -> OrgRole | None:
    db.expire_all()
    membership = org_service.get_membership(db, user)
    return membership.role if membership else None


@pytest.fixture
def team(db_session):
    """Two owners, an admin, two members."""
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER),
        "owner2": _person(db_session, "owner2@griddo.io", OrgRole.OWNER),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "admin2": _person(db_session, "admin2@griddo.io", OrgRole.ADMIN),
        "member": _person(db_session, "member@griddo.io", OrgRole.MEMBER),
        "member2": _person(db_session, "member2@griddo.io", OrgRole.MEMBER),
    }


def _set_role(client, actor: User, target: User, role: str):
    return client.patch(
        f"/api/v1/organization/members/{target.id}", json={"role": role}, headers=_headers(actor)
    )


class TestDefaultOrganization:
    def test_created_once_from_settings(self, db_session, monkeypatch):
        monkeypatch.setattr(settings, "organization_name", "Griddo")
        monkeypatch.setattr(settings, "organization_domain", "griddo.io")

        first = org_service.get_or_create_default_organization(db_session)
        second = org_service.get_or_create_default_organization(db_session)

        assert first.id == second.id
        assert (first.name, first.google_domain) == ("Griddo", "griddo.io")
        assert db_session.query(Organization).count() == 1

    @pytest.mark.usefixtures("allow_password_signup")
    def test_sign_up_joins_as_member(self, client, db_session):
        response = client.post(
            "/api/v1/auth/register", json={"email": "new@griddo.io", "password": "secret123"}
        )

        assert response.status_code == 201
        user = db_session.query(User).filter_by(email="new@griddo.io").one()
        assert _role(db_session, user) == OrgRole.MEMBER

    @pytest.mark.usefixtures("allow_password_signup")
    def test_configured_email_becomes_the_first_owner(self, client, db_session, monkeypatch):
        monkeypatch.setattr(settings, "bootstrap_owner_email", "boss@griddo.io")

        client.post("/api/v1/auth/register", json={"email": "early@griddo.io", "password": "x" * 8})
        client.post("/api/v1/auth/register", json={"email": "boss@griddo.io", "password": "x" * 8})

        users = {u.email: u for u in db_session.query(User).all()}
        assert _role(db_session, users["early@griddo.io"]) == OrgRole.MEMBER
        assert _role(db_session, users["boss@griddo.io"]) == OrgRole.OWNER

    def test_startup_adds_missing_memberships(self, db_session, monkeypatch):
        """Accounts created before organizations existed join at the next boot."""
        monkeypatch.setattr(settings, "bootstrap_owner_email", "boss@griddo.io")
        boss = _person(db_session, "boss@griddo.io", None)
        someone = _person(db_session, "someone@griddo.io", None)

        org_service.ensure_memberships(db_session)
        db_session.commit()

        assert _role(db_session, boss) == OrgRole.OWNER
        assert _role(db_session, someone) == OrgRole.MEMBER

    def test_startup_leaves_removed_people_out(self, client, db_session, team):
        """Removing someone closes their account; the next boot must not add it back."""
        client.delete(
            f"/api/v1/organization/members/{team['member'].id}", headers=_headers(team["admin"])
        )

        org_service.ensure_memberships(db_session)
        db_session.commit()

        assert _role(db_session, team["member"]) is None

    def test_configured_email_only_restores_an_owner_when_none_is_left(
        self, db_session, team, monkeypatch
    ):
        """Break-glass, not a veto: with owners in place, the configured email keeps its role."""
        monkeypatch.setattr(settings, "bootstrap_owner_email", team["member"].email)

        org_service.ensure_memberships(db_session)
        db_session.commit()

        assert _role(db_session, team["member"]) == OrgRole.MEMBER


class TestReadingTheOrganization:
    def test_anyone_in_it_sees_it_with_their_role(self, client, team):
        response = client.get("/api/v1/organization", headers=_headers(team["member"]))

        assert response.status_code == 200
        assert response.json()["role"] == "member"

    def test_anyone_in_it_sees_the_members(self, client, team):
        response = client.get("/api/v1/organization/members", headers=_headers(team["member"]))

        assert response.status_code == 200
        roles = {m["email"]: m["role"] for m in response.json()}
        assert roles["owner@griddo.io"] == "owner"
        assert roles["admin@griddo.io"] == "admin"
        assert len(roles) == 6


class TestChangingRoles:
    @pytest.mark.parametrize(
        ("target", "new_role"),
        [("member", "admin"), ("admin", "member"), ("member", "owner"), ("admin", "owner")],
    )
    def test_owner_changes_admins_and_members(self, client, db_session, team, target, new_role):
        response = _set_role(client, team["owner"], team[target], new_role)

        assert response.status_code == 200
        assert _role(db_session, team[target]) == OrgRole(new_role)

    def test_role_change_is_logged(self, client, team, capsys):
        capsys.readouterr()
        _set_role(client, team["owner"], team["member"], "admin")

        [line] = _events(capsys.readouterr().err, "org.role_changed")
        assert line["actor_id"] == str(team["owner"].id)
        assert line["user_id"] == str(team["member"].id)
        assert (line["from_role"], line["to_role"]) == ("member", "admin")

    @pytest.mark.parametrize(
        ("actor", "target", "new_role"),
        [
            ("admin", "member", "admin"),  # only owners promote
            ("admin", "admin2", "member"),  # admins can't demote each other
            ("admin", "owner", "member"),  # nor an owner
            ("member", "member2", "admin"),
            ("owner", "owner2", "member"),  # owners step down themselves
        ],
    )
    def test_everyone_else_is_refused(self, client, db_session, team, actor, target, new_role):
        before = _role(db_session, team[target])

        response = _set_role(client, team[actor], team[target], new_role)

        assert response.status_code == 403
        assert _role(db_session, team[target]) == before

    def test_nobody_raises_their_own_role(self, client, db_session, team):
        response = _set_role(client, team["admin"], team["admin"], "owner")

        assert response.status_code == 403
        assert _role(db_session, team["admin"]) == OrgRole.ADMIN

    def test_owner_steps_down_while_another_owner_remains(self, client, db_session, team):
        response = _set_role(client, team["owner"], team["owner"], "admin")

        assert response.status_code == 200
        assert _role(db_session, team["owner"]) == OrgRole.ADMIN

    def test_last_owner_cannot_step_down(self, client, db_session, team):
        assert _set_role(client, team["owner2"], team["owner2"], "admin").status_code == 200

        response = _set_role(client, team["owner"], team["owner"], "admin")

        assert response.status_code == 409
        assert _role(db_session, team["owner"]) == OrgRole.OWNER

    def test_unknown_person_is_404(self, client, team, db_session):
        outsider = _person(db_session, "outsider@example.com", None)

        assert _set_role(client, team["owner"], outsider, "admin").status_code == 404

    def test_unknown_role_is_422(self, client, team):
        assert _set_role(client, team["owner"], team["member"], "superuser").status_code == 422


class TestHandingOwnershipOver:
    def test_only_owner_hands_over_and_becomes_admin(self, client, db_session, team):
        client.patch(
            f"/api/v1/organization/members/{team['owner2'].id}",
            json={"role": "admin"},
            headers=_headers(team["owner2"]),
        )

        response = client.post(
            "/api/v1/organization/transfer-ownership",
            json={"user_id": str(team["member"].id)},
            headers=_headers(team["owner"]),
        )

        assert response.status_code == 200
        assert _role(db_session, team["member"]) == OrgRole.OWNER
        assert _role(db_session, team["owner"]) == OrgRole.ADMIN

    def test_non_owners_cannot_hand_it_over(self, client, db_session, team):
        response = client.post(
            "/api/v1/organization/transfer-ownership",
            json={"user_id": str(team["member"].id)},
            headers=_headers(team["admin"]),
        )

        assert response.status_code == 403
        assert _role(db_session, team["member"]) == OrgRole.MEMBER


class TestRemovingMembers:
    def _remove(self, client, actor: User, target: User):
        return client.delete(f"/api/v1/organization/members/{target.id}", headers=_headers(actor))

    def test_admin_removes_a_member_and_closes_the_account(self, client, db_session, team, capsys):
        team["member"].api_key = "key-to-revoke"
        db_session.commit()
        capsys.readouterr()

        response = self._remove(client, team["admin"], team["member"])

        assert response.status_code == 204
        db_session.expire_all()
        assert _role(db_session, team["member"]) is None
        assert team["member"].is_active is False
        assert team["member"].api_key is None
        [line] = _events(capsys.readouterr().err, "org.member_removed")
        assert line["user_id"] == str(team["member"].id)

    def test_removed_person_is_locked_out_at_once(self, client, team):
        """Their JWT is still unexpired, but the account is closed."""
        self._remove(client, team["admin"], team["member"])

        response = client.get("/api/v1/organization", headers=_headers(team["member"]))

        assert response.status_code == 403

    def test_owner_removes_an_admin(self, client, db_session, team):
        assert self._remove(client, team["owner"], team["admin"]).status_code == 204
        assert _role(db_session, team["admin"]) is None

    @pytest.mark.parametrize(
        ("actor", "target"),
        [("admin", "admin2"), ("admin", "owner"), ("owner", "owner2"), ("member", "member2")],
    )
    def test_equal_or_higher_roles_cannot_be_removed(self, client, db_session, team, actor, target):
        before = _role(db_session, team[target])

        assert self._remove(client, team[actor], team[target]).status_code == 403
        assert _role(db_session, team[target]) == before

    def test_nobody_removes_themselves_here(self, client, team):
        assert self._remove(client, team["admin"], team["admin"]).status_code == 400


def test_two_owners_stepping_down_at_once_leave_one(pg_engine):
    """The owner check locks the owner rows, so concurrent step-downs can't leave none."""
    from server.core.migrations import run_migrations

    run_migrations(pg_engine)
    make_session = sessionmaker(bind=pg_engine)
    with make_session() as db:
        first = _person(db, "first@griddo.io", OrgRole.OWNER)
        second = _person(db, "second@griddo.io", OrgRole.OWNER)
        first_id, second_id = first.id, second.id

    outcome: dict[str, object] = {}
    session_a = make_session()
    # First owner steps down and holds its transaction open.
    org_service.change_role(session_a, session_a.get(User, first_id), first_id, OrgRole.ADMIN)

    def second_steps_down():
        with make_session() as session_b:
            try:
                me = session_b.get(User, second_id)
                org_service.change_role(session_b, me, second_id, OrgRole.ADMIN)
                session_b.commit()
                outcome["second"] = "stepped down"
            except org_service.LastOwner:
                outcome["second"] = "refused"

    worker = threading.Thread(target=second_steps_down)
    worker.start()
    worker.join(timeout=2)  # with the lock, it waits here for the first transaction
    session_a.commit()
    session_a.close()
    worker.join(timeout=30)

    assert outcome["second"] == "refused"
    with make_session() as db:
        owners = db.query(OrganizationMember).filter_by(role=OrgRole.OWNER).count()
    assert owners == 1
