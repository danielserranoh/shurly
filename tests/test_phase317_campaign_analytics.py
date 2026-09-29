"""
Phase 3.17 — per-campaign analytics (ROADMAP 3.17.1): the header's all-time numbers, and the
series and breakdown of a link (3.16), over all of a campaign's recipients' links. A campaign
has one link per recipient, a row of its CSV.

"Clicked" is a recipient with at least one click, "Opened" one with at least one pixel open;
a recipient can be both. Each route answers for exactly the campaigns `/users` answers for.

"Now" is frozen at 2026-10-26 10:00 UTC.
"""

from datetime import datetime, timezone

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
from server.utils import local_days
from server.utils.domain import get_or_create_default_domain
from tests.test_phase316_link_analytics import CURL, IPHONE_SAFARI, NOW, WINDOWS_CHROME, _utc

ROUTES = ("totals", "timeseries", "breakdown")


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(local_days, "_now", lambda: NOW)


def _campaign(db, owner: User, name: str = "Q4 webinar", **fields) -> Campaign:
    campaign = Campaign(
        name=name,
        original_url="https://example.com",
        csv_columns=["name"],
        created_by=owner.id,
        **fields,
    )
    db.add(campaign)
    db.flush()
    return campaign


def _recipient(db, campaign: Campaign, code: str, name: str) -> URL:
    url = URL(
        short_code=code,
        original_url="https://example.com",
        url_type=URLType.CAMPAIGN,
        campaign_id=campaign.id,
        user_data={"name": name},
        created_by=campaign.created_by,
        organization_id=campaign.organization_id,
        domain_id=get_or_create_default_domain(db).id,
    )
    db.add(url)
    db.flush()
    return url


def _visit(db, url: URL, at: datetime, **fields) -> None:
    fields.setdefault("user_agent", WINDOWS_CHROME)
    db.add(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip="203.0.113.0",
            visited_at=at.astimezone(timezone.utc).replace(tzinfo=None),
            **fields,
        )
    )


def _get(client, headers, campaign, route: str, **params):
    return client.get(
        f"/api/v1/analytics/campaigns/{campaign.id}/{route}", params=params, headers=headers
    )


@pytest.fixture
def campaign(db_session, test_user) -> Campaign:
    """Ana clicked twice and opened once; Luis only opened, twice; Marta did neither."""
    campaign = _campaign(db_session, test_user)
    ana = _recipient(db_session, campaign, "q4-ana", "Ana")
    luis = _recipient(db_session, campaign, "q4-luis", "Luis")
    _recipient(db_session, campaign, "q4-marta", "Marta")
    _visit(db_session, ana, _utc(2026, 10, 20, 9), country="ES")
    _visit(db_session, ana, _utc(2026, 10, 25, 21, 30), country="ES", user_agent=IPHONE_SAFARI)
    _visit(db_session, ana, _utc(2026, 10, 24, 8), is_pixel=True)
    _visit(db_session, luis, _utc(2026, 10, 22, 8), is_pixel=True, country="PT")
    _visit(db_session, luis, _utc(2026, 10, 25, 8), is_pixel=True, country="PT")
    _visit(db_session, ana, _utc(2026, 10, 26, 9), is_bot=True, user_agent=CURL, country="US")
    _visit(db_session, luis, _utc(2026, 10, 23, 9), is_pixel=True, is_bot=True, user_agent=CURL)

    # Not the campaign's: a link of its own, and another campaign's recipient.
    other = _campaign(db_session, test_user, name="Other")
    elsewhere = [
        _recipient(db_session, other, "other-1", "Pere"),
        URL(
            short_code="solo",
            original_url="https://example.com",
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        ),
    ]
    db_session.add(elsewhere[1])
    db_session.flush()
    for url in elsewhere:
        _visit(db_session, url, _utc(2026, 10, 25, 12), country="FR")
        _visit(db_session, url, _utc(2026, 10, 25, 12), is_pixel=True)
    db_session.commit()
    return campaign


class TestTotals:
    def test_the_headers_all_time_numbers(self, client, auth_headers, campaign):
        body = _get(client, auth_headers, campaign, "totals", tz="Europe/Madrid").json()

        assert body == {
            "campaign_id": str(campaign.id),
            "campaign_name": "Q4 webinar",
            "timezone": "Europe/Madrid",
            "recipients": 3,
            "clicks": 2,
            "opens": 3,  # neither the other campaign's nor the bot's pixel hit
            "clicked": 1,  # Ana
            "opened": 2,  # Ana and Luis, however many times; Ana is both
            "click_rate": 0.3333,
            "open_rate": 0.6667,
            "countries": 1,
            "last_click_at": "2026-10-25T22:30:00+01:00",  # not the bot's, the next morning
        }

    def test_a_campaign_without_recipients(self, client, db_session, auth_headers, test_user):
        empty = _campaign(db_session, test_user, name="Empty")
        db_session.commit()

        body = _get(client, auth_headers, empty, "totals").json()

        assert (body["recipients"], body["clicked"], body["click_rate"], body["open_rate"]) == (
            0,
            0,
            0.0,
            0.0,
        )
        assert body["last_click_at"] is None


class TestTimeseries:
    def test_the_campaigns_links_only(self, client, auth_headers, campaign):
        body = _get(client, auth_headers, campaign, "timeseries", period=7).json()

        assert (body["campaign_id"], body["campaign_name"]) == (str(campaign.id), "Q4 webinar")
        assert (body["from"], body["to"], body["group_by"]) == ("2026-10-20", "2026-10-26", "day")
        assert {
            s["start"]: (s["clicks"], s["opens"])
            for s in body["stats"]
            if s["clicks"] or s["opens"]
        } == {
            "2026-10-20": (1, 0),
            "2026-10-22": (0, 1),
            "2026-10-24": (0, 1),
            "2026-10-25": (1, 1),
        }
        assert (body["clicks"], body["opens"]) == (2, 3)
        assert sum(h["clicks"] for h in body["hour_of_day"]) == 2
        assert sum(d["opens"] for d in body["day_of_week"]) == 3

    def test_weeks(self, client, auth_headers, campaign):
        body = _get(client, auth_headers, campaign, "timeseries", period=14, group_by="week").json()

        assert [(s["start"], s["end"], s["clicks"], s["opens"]) for s in body["stats"]] == [
            ("2026-10-13", "2026-10-18", 0, 0),
            ("2026-10-19", "2026-10-25", 2, 3),
            ("2026-10-26", "2026-10-26", 0, 0),
        ]


class TestBreakdown:
    @pytest.mark.parametrize(
        "kind, total, countries",
        [
            ("clicks", 2, [("ES", 2)]),
            ("opens", 3, [("PT", 2), ("Unknown", 1)]),
            ("bots", 2, [("Unknown", 1), ("US", 1)]),
            ("all", 7, [("ES", 2), ("PT", 2), ("Unknown", 2), ("US", 1)]),
        ],
    )
    def test_the_campaigns_links_by_kind(
        self, client, auth_headers, campaign, kind, total, countries
    ):
        body = _get(client, auth_headers, campaign, "breakdown", type=kind).json()

        assert (body["campaign_id"], body["type"], body["total"]) == (str(campaign.id), kind, total)
        assert [(c["name"], c["count"]) for c in body["countries"]] == countries

    def test_every_dimension(self, client, auth_headers, campaign):
        body = _get(client, auth_headers, campaign, "breakdown").json()

        assert [(o["name"], o["count"]) for o in body["os"]] == [("iOS", 1), ("Windows", 1)]
        assert [(d["name"], d["count"]) for d in body["devices"]] == [("desktop", 1), ("mobile", 1)]
        assert [(r["name"], r["share"]) for r in body["referrers"]] == [("Direct", 1.0)]

    def test_the_period(self, client, auth_headers, campaign):
        body = _get(
            client,
            auth_headers,
            campaign,
            "breakdown",
            **{"from": "2026-10-21", "to": "2026-10-24"},
        )

        assert (body.json()["total"], body.json()["from"]) == (0, "2026-10-21")


class TestScope:
    """Exactly `/users`' rule: the organization's campaigns, whatever the role, and one's own."""

    @pytest.fixture
    def people(self, db_session, test_user):
        organization = Organization(name="Griddo")
        member = User(email="member@griddo.io", password_hash="x", is_active=True)
        outsider = User(email="outsider@example.com", password_hash="x", is_active=True)
        db_session.add_all([organization, member, outsider])
        db_session.flush()
        for user, role in ((test_user, OrgRole.OWNER), (member, OrgRole.MEMBER)):
            db_session.add(
                OrganizationMember(organization_id=organization.id, user_id=user.id, role=role)
            )
        shared = _campaign(db_session, test_user, name="Shared", organization_id=organization.id)
        personal = _campaign(db_session, test_user, name="Mine")
        db_session.commit()
        return {"member": member, "outsider": outsider, "shared": shared, "personal": personal}

    @staticmethod
    def _as(user: User) -> dict:
        return {"Authorization": f"Bearer {create_access_token(data={'sub': user.email})}"}

    @pytest.mark.parametrize(
        "who, which, expected",
        [
            ("member", "shared", 200),
            ("member", "personal", 404),
            ("outsider", "shared", 404),
            ("outsider", "personal", 404),
        ],
    )
    def test_as_users_decides(self, client, people, who, which, expected):
        headers, campaign = self._as(people[who]), people[which]

        assert _get(client, headers, campaign, "users").status_code == expected
        for route in ROUTES:
            assert _get(client, headers, campaign, route).status_code == expected, route

    def test_an_id_that_isnt_one(self, client, auth_headers):
        for route in ("users", *ROUTES):
            response = client.get(f"/api/v1/analytics/campaigns/nope/{route}", headers=auth_headers)
            assert response.status_code == 400, route

    def test_the_period_rules_hold(self, client, auth_headers, campaign):
        for route in ("timeseries", "breakdown"):
            assert _get(client, auth_headers, campaign, route, period=0).status_code == 422
