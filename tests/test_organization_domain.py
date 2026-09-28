"""
Only accounts on the organization's email domain join it.

Sign-up is still open to anyone (retro R1; 3.13 replaces it with Google
sign-in). Since 3.14.2 every new account joined the organization, and since
3.14.3 every member sees all of the organization's links and campaigns — and
campaigns carry their recipients' names, companies and emails. Together that
let anyone register with any address and read or export the team's data.

`ORGANIZATION_DOMAIN` (default `griddo.io`) now gates joining: an account
outside it still works, with only its own personal links. An empty value
lets any account join (single-tenant setups that don't care).
"""

from __future__ import annotations

import pytest
from sqlalchemy import func

from server.core.auth import create_access_token, hash_password
from server.core.config import settings
from server.core.models import OrganizationMember, OrgRole, User
from server.utils import organization as org_service

_PASSWORD_HASH = hash_password("secret123")


@pytest.fixture(autouse=True)
def _griddo_domain(monkeypatch):
    monkeypatch.setattr(settings, "organization_domain", "griddo.io")
    monkeypatch.setattr(settings, "bootstrap_owner_email", "")


def _headers(email: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': email})}"}


def _register(client, email: str):
    return client.post("/api/v1/auth/register", json={"email": email, "password": "secret123"})


def _membership(db, email: str) -> OrganizationMember | None:
    # Case-insensitive: the email schema normalizes the domain part on its own.
    user = db.query(User).filter(func.lower(User.email) == email.lower()).one()
    return db.query(OrganizationMember).filter_by(user_id=user.id).one_or_none()


@pytest.mark.usefixtures("allow_password_signup")
class TestSignUp:
    def test_an_address_on_the_domain_joins(self, client, db_session):
        assert _register(client, "alice@griddo.io").status_code == 201
        assert _membership(db_session, "alice@griddo.io").role == OrgRole.MEMBER

    def test_the_domain_match_ignores_case(self, client, db_session):
        assert _register(client, "Bob@GRIDDO.io").status_code == 201
        assert _membership(db_session, "Bob@GRIDDO.io") is not None

    @pytest.mark.parametrize(
        "email",
        [
            "outsider@example.com",
            "x@evilgriddo.io",  # ends with the domain, isn't it
            "x@griddo.io.evil.com",  # contains it
            "x@eu.griddo.io",  # a subdomain is a different domain
        ],
    )
    def test_an_address_off_the_domain_gets_an_account_but_no_membership(
        self, client, db_session, email
    ):
        assert _register(client, email).status_code == 201
        assert _membership(db_session, email) is None

    def test_an_empty_domain_lets_anyone_join(self, client, db_session, monkeypatch):
        monkeypatch.setattr(settings, "organization_domain", "")
        assert _register(client, "anyone@example.com").status_code == 201
        assert _membership(db_session, "anyone@example.com") is not None

    def test_the_bootstrap_owner_must_be_on_the_domain_too(self, client, db_session, monkeypatch):
        monkeypatch.setattr(settings, "bootstrap_owner_email", "boss@example.com")
        assert _register(client, "boss@example.com").status_code == 201
        assert _membership(db_session, "boss@example.com") is None


@pytest.mark.usefixtures("allow_password_signup")
class TestAnOutsiderCannotReadTheTeam:
    """The attack this closes: register with any address, then read the team's data."""

    @pytest.fixture
    def team_link(self, client, db_session):
        assert _register(client, "alice@griddo.io").status_code == 201
        response = client.post(
            "/api/v1/urls",
            json={"url": "https://example.org/campaign", "title": "Team link"},
            headers=_headers("alice@griddo.io"),
        )
        assert response.status_code == 201, response.text
        return response.json()["short_code"]

    @pytest.fixture
    def outsider(self, client):
        assert _register(client, "outsider@example.com").status_code == 201
        return _headers("outsider@example.com")

    def test_members_list_is_not_readable(self, client, team_link, outsider):
        response = client.get("/api/v1/organization/members", headers=outsider)
        assert response.status_code != 200
        assert "alice@griddo.io" not in response.text

    def test_the_teams_links_are_not_listed(self, client, team_link, outsider):
        response = client.get("/api/v1/urls", headers=outsider)
        assert response.status_code == 200
        assert team_link not in response.text

    def test_a_team_link_is_not_found(self, client, team_link, outsider):
        assert client.get(f"/api/v1/urls/{team_link}", headers=outsider).status_code == 404

    def test_the_outsiders_own_links_still_work_as_personal(self, client, outsider):
        response = client.post(
            "/api/v1/urls", json={"url": "https://example.org/mine"}, headers=outsider
        )
        assert response.status_code == 201, response.text
        assert response.json()["visibility"] == "personal"


class TestStartup:
    def test_existing_accounts_off_the_domain_stay_out(self, db_session):
        for email in ("carol@griddo.io", "mallory@example.com"):
            db_session.add(User(email=email, password_hash=_PASSWORD_HASH, is_active=True))
        db_session.commit()

        org_service.ensure_memberships(db_session)
        db_session.commit()

        assert _membership(db_session, "carol@griddo.io") is not None
        assert _membership(db_session, "mallory@example.com") is None
