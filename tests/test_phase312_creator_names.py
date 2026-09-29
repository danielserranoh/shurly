"""
"Created by" by name (after Phase 3.12's profile): campaign and link responses keep
`created_by_email` and gain the creator's `created_by_first_name` and `created_by_last_name`,
null without a profile. The lists load every creator's profile with the page: one query in
all, never one per item or per creator.
"""

import pytest
from sqlalchemy import event

from server.app import urls as urls_module
from server.core.auth import create_access_token, hash_password
from server.core.models import URL, Campaign, OrganizationMember, OrgRole, User, UserProfile
from server.utils import organization as org_service
from server.utils.domain import get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata

_PASSWORD_HASH = hash_password("secret123")


def _person(db, email, *, first=None, last=None) -> User:
    user = User(email=email, password_hash=_PASSWORD_HASH, is_active=True)
    db.add(user)
    db.flush()
    if first or last:
        db.add(UserProfile(user_id=user.id, first_name=first, last_name=last))
    db.commit()
    return user


def _campaign(db, creator: User, name: str) -> Campaign:
    campaign = Campaign(
        name=name, original_url="https://example.com", csv_columns=["name"], created_by=creator.id
    )
    db.add(campaign)
    db.commit()
    return campaign


def _creator(item: dict) -> tuple:
    return (item["created_by_email"], item["created_by_first_name"], item["created_by_last_name"])


def _selects(db, request) -> list[str]:
    """The SELECTs `request()` makes."""
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
    return selects


def _profile_queries(selects: list[str]) -> int:
    return sum("FROM user_profiles" in select for select in selects)


def _member(db, organization, n: int) -> User:
    """A member of `organization` with a name."""
    person = _person(db, f"m{n}@griddo.io", first=f"Member {n}")
    db.add(
        OrganizationMember(organization_id=organization.id, user_id=person.id, role=OrgRole.MEMBER)
    )
    db.commit()
    return person


class TestCampaigns:
    def test_the_list_names_each_creator(self, client, auth_headers, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana", last_name="García"))
        db_session.commit()
        _campaign(db_session, test_user, "Mine")

        campaigns = client.get("/api/v1/campaigns", headers=auth_headers).json()["campaigns"]

        assert [_creator(c) for c in campaigns] == [(test_user.email, "Ana", "García")]

    def test_null_names_without_a_profile(self, client, auth_headers, db_session, test_user):
        _campaign(db_session, test_user, "Mine")

        campaign = client.get("/api/v1/campaigns", headers=auth_headers).json()["campaigns"][0]

        assert _creator(campaign) == (test_user.email, None, None)

    def test_the_detail_too(self, client, auth_headers, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana"))
        db_session.commit()
        campaign = _campaign(db_session, test_user, "Mine")

        detail = client.get(f"/api/v1/campaigns/{campaign.id}", headers=auth_headers).json()

        assert _creator(detail) == (test_user.email, "Ana", None)

    def test_and_the_answer_to_creating_one(self, client, auth_headers, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana", last_name="García"))
        db_session.commit()

        response = client.post(
            "/api/v1/campaigns",
            headers=auth_headers,
            json={"name": "New", "original_url": "https://example.com", "csv_data": "name\nBea"},
        )

        assert response.status_code == 201, response.text
        assert _creator(response.json()) == (test_user.email, "Ana", "García")

    def test_the_creators_profiles_load_with_the_page(self, client, db_session):
        """The organization's campaigns, each by a different member with a profile: their
        creators and profiles load with the page, not one query per campaign."""
        organization = org_service.get_or_create_default_organization(db_session)

        def member_campaign(n: int) -> User:
            person = _person(db_session, f"m{n}@griddo.io", first=f"Member {n}")
            db_session.add(
                OrganizationMember(
                    organization_id=organization.id, user_id=person.id, role=OrgRole.MEMBER
                )
            )
            db_session.add(
                Campaign(
                    name=f"Campaign {n}",
                    original_url="https://example.com",
                    csv_columns=["name"],
                    created_by=person.id,
                    organization_id=organization.id,
                )
            )
            db_session.commit()
            return person

        viewer = member_campaign(0)
        member_campaign(1)
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': viewer.email})}"}
        list_page = lambda: client.get("/api/v1/campaigns", headers=headers)  # noqa: E731
        few = len(_selects(db_session, list_page))
        for n in range(2, 8):
            member_campaign(n)
        db_session.expire_all()

        response = client.get("/api/v1/campaigns", headers=headers).json()
        assert {c["created_by_first_name"] for c in response["campaigns"]} == {
            f"Member {n}" for n in range(8)
        }
        db_session.expire_all()
        selects = _selects(db_session, list_page)
        assert len(selects) == few
        assert _profile_queries(selects) == 1


def _link(db, creator: User, code: str, **fields) -> URL:
    url = URL(
        short_code=code,
        original_url="https://example.com",
        created_by=creator.id,
        domain_id=get_or_create_default_domain(db).id,
        **fields,
    )
    db.add(url)
    db.commit()
    return url


@pytest.fixture
def no_og_fetch(monkeypatch):
    """Creating a link fetches its preview: never over the network in tests."""

    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


class TestLinks:
    def test_the_list_names_each_creator(self, client, auth_headers, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana", last_name="García"))
        db_session.commit()
        _link(db_session, test_user, "mine1")

        links = client.get("/api/v1/urls", headers=auth_headers).json()["urls"]

        assert [_creator(link) for link in links] == [(test_user.email, "Ana", "García")]

    def test_null_names_without_a_profile(self, client, auth_headers, db_session, test_user):
        _link(db_session, test_user, "mine1")

        link = client.get("/api/v1/urls", headers=auth_headers).json()["urls"][0]

        assert _creator(link) == (test_user.email, None, None)

    def test_the_detail_too(self, client, auth_headers, db_session, test_user):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana"))
        db_session.commit()
        _link(db_session, test_user, "mine1")

        detail = client.get("/api/v1/urls/mine1", headers=auth_headers).json()

        assert _creator(detail) == (test_user.email, "Ana", None)

    def test_and_the_answers_to_creating_and_editing_one(
        self, client, auth_headers, db_session, test_user, no_og_fetch
    ):
        db_session.add(UserProfile(user_id=test_user.id, first_name="Ana", last_name="García"))
        db_session.commit()

        created = client.post(
            "/api/v1/urls", headers=auth_headers, json={"url": "https://example.com/new"}
        )
        assert created.status_code == 201, created.text
        edited = client.patch(
            f"/api/v1/urls/{created.json()['short_code']}",
            headers=auth_headers,
            json={"title": "Renamed"},
        )

        assert _creator(created.json()) == (test_user.email, "Ana", "García")
        assert _creator(edited.json()) == (test_user.email, "Ana", "García")

    def test_the_creators_profiles_load_with_the_page(self, client, db_session):
        """The organization's links, each by a different member with a profile: one query
        loads every creator's profile, however many creators the page has."""
        organization = org_service.get_or_create_default_organization(db_session)

        def member_link(n: int) -> User:
            person = _member(db_session, organization, n)
            _link(db_session, person, f"link{n}", organization_id=organization.id)
            return person

        viewer = member_link(0)
        member_link(1)
        headers = {"Authorization": f"Bearer {create_access_token(data={'sub': viewer.email})}"}
        list_page = lambda: client.get("/api/v1/urls", headers=headers)  # noqa: E731
        few = len(_selects(db_session, list_page))
        for n in range(2, 8):
            member_link(n)
        db_session.expire_all()

        response = client.get("/api/v1/urls", headers=headers).json()
        assert {link["created_by_first_name"] for link in response["urls"]} == {
            f"Member {n}" for n in range(8)
        }
        db_session.expire_all()
        selects = _selects(db_session, list_page)
        assert len(selects) == few
        assert _profile_queries(selects) == 1
