"""
"Created by" by name (after Phase 3.12's profile): campaign responses keep `created_by_email`
and gain the creator's `created_by_first_name` and `created_by_last_name`, null without a
profile. The list loads every creator's profile with the page, never one query per campaign.

Links follow in their own PR, after 8.3 reshapes the URL responses.
"""

from sqlalchemy import event

from server.core.auth import create_access_token, hash_password
from server.core.models import Campaign, OrganizationMember, OrgRole, User, UserProfile
from server.utils import organization as org_service

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
        few = _queries(db_session, list_page)
        for n in range(2, 8):
            member_campaign(n)
        db_session.expire_all()

        response = client.get("/api/v1/campaigns", headers=headers).json()
        assert {c["created_by_first_name"] for c in response["campaigns"]} == {
            f"Member {n}" for n in range(8)
        }
        db_session.expire_all()
        assert _queries(db_session, list_page) == few
