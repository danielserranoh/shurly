"""
Personal data at runtime (docs/PERSONAL_DATA.md, part b): for every route whose row says it
returns recipients' rows, their activity or visits, the table's "who" holds.

An organization's campaign has one recipient, whose CSV row carries a marker, and some visits.
- An outsider, signed in but from another organization, gets a 404 for the campaign or its
  link, and never sees the marker in a list.
- A plain member of the organization gets it, the marker included where the row says the
  route returns recipients' rows.
- A campaign that is its creator's own stays hidden from that member.
- Phase 10.1 — a route for the organization's owners and admins (a service account's links):
  the owner gets it, a plain member a 403. The shared campaign's link was made by the
  organization's service account, which these routes address as `{account_id}`.

The routes are read from the table, so a new one is checked as soon as its row says what it
returns.
"""

from datetime import datetime, timedelta

import pytest

from server.core.auth import create_access_token
from server.core.models import (
    URL,
    Campaign,
    Organization,
    OrganizationMember,
    OrgRole,
    URLType,
    User,
    Visitor,
)
from server.utils.domain import get_or_create_default_domain
from tests.test_personal_data_inventory import _rows

MARKER = "zelda.marker"  # in the recipient's row: it must never reach an outsider
CHECKED = ("**recipients' rows**", "**recipients' activity**", "**visits**")


def _checked_routes() -> list[str]:
    """Every GET whose row returns people's data of these kinds, and isn't public."""
    return sorted(
        key
        for key, row in _rows().items()
        if key.startswith("GET ")
        and row["guard"].strip() != "public"
        and any(kind in row["data"] for kind in CHECKED)
    )


ROUTES = _checked_routes()


def _as(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}


def _campaign(db, owner: User, organization_id, code: str) -> Campaign:
    campaign = Campaign(
        name=f"Audit {code}",
        original_url="https://example.com",
        csv_columns=["name", "email"],
        created_by=owner.id,
        organization_id=organization_id,
    )
    db.add(campaign)
    db.flush()
    link = URL(
        short_code=code,
        original_url="https://example.com",
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data={"name": "Zelda", "email": f"{MARKER}@example.com"},
        created_by=owner.id,
        organization_id=organization_id,
        domain_id=get_or_create_default_domain(db).id,
    )
    db.add(link)
    db.flush()
    now = datetime.utcnow()
    for minutes, is_pixel in ((5, False), (65, False), (125, True)):
        db.add(
            Visitor(
                url_id=link.id,
                short_code=code,
                ip="203.0.113.0",
                country="ES",
                user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/129.0 Safari/537.36",
                is_pixel=is_pixel,
                visited_at=now - timedelta(minutes=minutes),
            )
        )
    return campaign


@pytest.fixture
def world(db_session) -> dict:
    griddo, other = Organization(name="Griddo"), Organization(name="Other")
    owner = User(email="owner@griddo.io", password_hash="x", is_active=True)
    member = User(email="member@griddo.io", password_hash="x", is_active=True)
    outsider = User(email="someone@other.example", password_hash="x", is_active=True)
    service = User(
        email="audit@service.invalid", kind="service", display_name="Audit", is_active=True
    )
    db_session.add_all([griddo, other, owner, member, outsider, service])
    db_session.flush()
    for organization, user, role in (
        (griddo, owner, OrgRole.OWNER),
        (griddo, member, OrgRole.MEMBER),
        (other, outsider, OrgRole.OWNER),
        (griddo, service, OrgRole.MEMBER),
    ):
        db_session.add(
            OrganizationMember(organization_id=organization.id, user_id=user.id, role=role)
        )
    shared = _campaign(db_session, owner, griddo.id, "aud-shared")
    personal = _campaign(db_session, owner, None, "aud-personal")
    db_session.flush()
    # Phase 10.1 — the shared campaign's link was made by the organization's service account.
    db_session.query(URL).filter(URL.short_code == "aud-shared").update(
        {URL.via_service_account_id: service.id}
    )
    db_session.commit()
    _SERVICE["id"] = service.id
    return {
        "owner": owner,
        "member": member,
        "outsider": outsider,
        "shared": (shared, "aud-shared"),
        "personal": (personal, "aud-personal"),
    }


_SERVICE: dict = {}


def _path(route: str, campaign: Campaign, code: str) -> str:
    return (
        route.split(" ", 1)[1]
        .replace("{campaign_id}", str(campaign.id))
        .replace("{short_code}", code)
        .replace("{account_id}", str(_SERVICE.get("id")))
    )


def _for_owners_and_admins(route: str) -> bool:
    """Phase 10.1 — a route only the organization's owners and admins read."""
    return _rows()[route]["who"].strip().startswith("an owner or admin")


def _returns_rows(route: str) -> bool:
    return "**recipients' rows**" in _rows()[route]["data"]


def test_the_table_names_the_routes_to_check():
    """If this list empties, the table's categories have drifted from these tests'."""
    assert "GET /api/v1/analytics/campaigns/{campaign_id}/recipients" in ROUTES
    assert "GET /api/v1/analytics/urls/{short_code}/visits" in ROUTES
    assert "GET /api/v1/campaigns/{campaign_id}/export" in ROUTES
    assert "GET /api/v1/urls" in ROUTES


@pytest.mark.parametrize("route", ROUTES)
def test_an_outsider_never_gets_it(client, world, route):
    campaign, code = world["shared"]
    response = client.get(_path(route, campaign, code), headers=_as(world["outsider"]))

    if "{" in route:  # one campaign or link: it doesn't exist, for them
        assert response.status_code == 404, response.text
    else:  # a list: theirs, without the organization's
        assert response.status_code == 200, response.text
        assert MARKER not in response.text and code not in response.text


@pytest.mark.parametrize("route", ROUTES)
def test_a_member_gets_it(client, world, route):
    """Or, for a route of the owners and admins, the owner does and a member gets a 403."""
    campaign, code = world["shared"]
    reader = world["owner"] if _for_owners_and_admins(route) else world["member"]
    response = client.get(_path(route, campaign, code), headers=_as(reader))

    assert response.status_code == 200, response.text
    if _returns_rows(route):
        assert MARKER in response.text
    if _for_owners_and_admins(route):
        refused = client.get(_path(route, campaign, code), headers=_as(world["member"]))
        assert refused.status_code == 403, refused.text


# A service account's links are never personal (10.1): its routes have no personal campaign.
@pytest.mark.parametrize(
    "route", [route for route in ROUTES if "{" in route and "{account_id}" not in route]
)
def test_a_personal_campaign_stays_its_creators(client, world, route):
    campaign, code = world["personal"]

    member = client.get(_path(route, campaign, code), headers=_as(world["member"]))
    owner = client.get(_path(route, campaign, code), headers=_as(world["owner"]))

    assert (member.status_code, owner.status_code) == (404, 200), route
