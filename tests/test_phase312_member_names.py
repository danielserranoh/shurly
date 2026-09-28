"""
Names in Settings → Organization (after Phase 3.12's profile).

The members, and the people removed from the organization, come with their first and last
names: null without a profile, the email as ever. The profiles are loaded with the list,
never one query per person. The order stays by email.
"""

import pytest
from sqlalchemy import event

from server.core.auth import create_access_token, hash_password
from server.core.config import settings
from server.core.models import OrganizationMember, OrgRole, User, UserProfile
from server.utils import organization as org_service

# bcrypt is slow on purpose; hash once for every user these tests create.
_PASSWORD_HASH = hash_password("secret123")


@pytest.fixture(autouse=True)
def organization_domain(monkeypatch):
    monkeypatch.setattr(settings, "organization_domain", "griddo.io")


def _person(db, email, role=None, *, first=None, last=None, active=True) -> User:
    """A user; with a role, a member of the default organization; with a name, a profile."""
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=active)
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


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


def _names(people: list[dict]) -> list[tuple]:
    return [(p["email"], p["first_name"], p["last_name"]) for p in people]


def _queries(db, request) -> int:
    """How many SELECTs `request()` makes."""
    selects = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", record)
    try:
        request()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(selects)


class TestMembers:
    def test_come_with_their_names(self, client, db_session):
        owner = _person(db_session, "owner@griddo.io", OrgRole.OWNER, first="Ana", last="García")
        _person(db_session, "bea@griddo.io", OrgRole.MEMBER, first="Bea")
        _person(db_session, "carl@griddo.io", OrgRole.MEMBER)

        members = client.get("/api/v1/organization/members", headers=_headers(owner)).json()

        assert _names(members) == [
            ("bea@griddo.io", "Bea", None),
            ("carl@griddo.io", None, None),
            ("owner@griddo.io", "Ana", "García"),
        ]

    def test_their_profiles_load_with_the_list(self, client, db_session):
        owner = _person(db_session, "owner@griddo.io", OrgRole.OWNER, first="Ana")
        _person(db_session, "m1@griddo.io", OrgRole.MEMBER, first="One")
        list_members = lambda: client.get("/api/v1/organization/members", headers=_headers(owner))  # noqa: E731
        few = _queries(db_session, list_members)
        for n in range(2, 7):
            _person(db_session, f"m{n}@griddo.io", OrgRole.MEMBER, first=f"Member {n}")
        db_session.expire_all()

        assert _queries(db_session, list_members) == few

    def test_a_role_change_answers_with_the_name(self, client, db_session):
        owner = _person(db_session, "owner@griddo.io", OrgRole.OWNER)
        bea = _person(db_session, "bea@griddo.io", OrgRole.MEMBER, first="Bea", last="Ruiz")

        response = client.patch(
            f"/api/v1/organization/members/{bea.id}",
            json={"role": "admin"},
            headers=_headers(owner),
        )

        assert response.status_code == 200
        assert (response.json()["first_name"], response.json()["last_name"]) == ("Bea", "Ruiz")


class TestRemovedPeople:
    def test_come_with_their_names(self, client, db_session):
        owner = _person(db_session, "owner@griddo.io", OrgRole.OWNER)
        _person(db_session, "gone@griddo.io", first="Dani", last="Serra", active=False)
        _person(db_session, "gone2@griddo.io", active=False)

        removed = client.get("/api/v1/organization/removed-members", headers=_headers(owner)).json()

        assert sorted(_names(removed)) == [
            ("gone2@griddo.io", None, None),
            ("gone@griddo.io", "Dani", "Serra"),
        ]

    def test_their_profiles_load_with_the_list(self, client, db_session):
        owner = _person(db_session, "owner@griddo.io", OrgRole.OWNER)
        _person(db_session, "gone0@griddo.io", first="Zero", active=False)
        list_removed = lambda: client.get(  # noqa: E731
            "/api/v1/organization/removed-members", headers=_headers(owner)
        )
        few = _queries(db_session, list_removed)
        for n in range(1, 5):
            _person(db_session, f"gone{n}@griddo.io", first=f"Gone {n}", active=False)
        db_session.expire_all()

        assert _queries(db_session, list_removed) == few
