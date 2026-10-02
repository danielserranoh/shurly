"""
A link's analytics count its own visits: they're keyed on the link (`visits.url_id`), never
on its code. The same code can name two links on two domains (at the Phase 8 cutover, Shlink's
arrived on go.griddo.io while test links lived on another domain); keyed on the code, their
visits would mix. `visits.short_code` stays, for orphan visits and debugging.

And the MCP's analytics summary counts clicks the way the app does: a tracking-pixel hit is
never a click, even with bots included.
"""

from datetime import datetime, timedelta, timezone

import pytest

from server.core.auth import create_access_token, hash_password
from server.core.models import URL, Campaign, Domain, URLType, User, Visitor
from server.utils.domain import get_or_create_default_domain

NOW = datetime.now(timezone.utc).replace(tzinfo=None)


def _visits(db, url: URL, count: int, country: str, **flags):
    db.add_all(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip=f"203.0.113.{n}",
            country=country,
            visited_at=NOW - timedelta(minutes=n + 1),
            **flags,
        )
        for n in range(count)
    )
    db.commit()


@pytest.fixture
def two_links(db_session, test_user):
    """ "dup" on two domains: test_user's link on the default one, and someone else's on
    go.griddo.io. Each sees only their own (both are personal)."""
    other = User(email="other@example.com", password_hash=hash_password("other-pass-1"))
    go = Domain(hostname="go.griddo.io", is_default=False)
    db_session.add_all([other, go])
    db_session.commit()
    mine = URL(
        short_code="dup",
        original_url="https://example.com/mine",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    theirs = URL(
        short_code="dup",
        original_url="https://example.com/theirs",
        created_by=other.id,
        domain_id=go.id,
    )
    db_session.add_all([mine, theirs])
    db_session.commit()
    _visits(db_session, mine, 1, "Spain")
    _visits(db_session, theirs, 3, "France")
    other_headers = {"Authorization": f"Bearer {create_access_token(data={'sub': other.email})}"}
    return mine, theirs, other_headers


class TestTheSameCodeOnTwoDomains:
    @pytest.mark.parametrize("path", ["daily", "weekly", "geo"])
    def test_each_link_counts_its_own_visits(self, client, auth_headers, two_links, path):
        _mine, _theirs, other_headers = two_links

        mine = client.get(f"/api/v1/analytics/urls/dup/{path}", headers=auth_headers).json()
        theirs = client.get(f"/api/v1/analytics/urls/dup/{path}", headers=other_headers).json()

        assert (mine["total_clicks"], theirs["total_clicks"]) == (1, 3)

    def test_the_countries_are_the_links(self, client, auth_headers, two_links):
        _mine, _theirs, other_headers = two_links

        mine = client.get("/api/v1/analytics/urls/dup/geo", headers=auth_headers).json()
        theirs = client.get("/api/v1/analytics/urls/dup/geo", headers=other_headers).json()

        assert [(s["country"], s["clicks"]) for s in mine["stats"]] == [("Spain", 1)]
        assert [(s["country"], s["clicks"]) for s in theirs["stats"]] == [("France", 3)]

    def test_the_csv_too(self, client, auth_headers, two_links):
        response = client.get(
            "/api/v1/analytics/urls/dup/daily", params={"format": "csv"}, headers=auth_headers
        )

        clicks = [int(line.split(",")[1]) for line in response.text.splitlines()[1:]]
        assert sum(clicks) == 1

    def test_a_campaigns_timeline_counts_its_links_only(
        self, client, auth_headers, db_session, test_user, two_links
    ):
        _mine, theirs, _other_headers = two_links
        campaign = Campaign(
            name="Q4",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()
        member = URL(
            short_code="cmp1",
            original_url="https://example.com",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"name": "Ana"},
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
        db_session.add(member)
        db_session.commit()
        # Someone else's link with the campaign link's code, on go.griddo.io.
        stray = URL(
            short_code="cmp1",
            original_url="https://example.com/stray",
            created_by=theirs.created_by,
            domain_id=theirs.domain_id,
        )
        db_session.add(stray)
        db_session.commit()
        _visits(db_session, member, 2, "Spain")
        _visits(db_session, stray, 5, "France")

        data = client.get(
            f"/api/v1/analytics/campaigns/{campaign.id}/summary", headers=auth_headers
        ).json()

        assert data["total_clicks"] == 2
        assert sum(day["clicks"] for day in data["daily_timeline"]) == 2

    def test_the_mcp_summary_too(self, db_session, test_user, two_links):
        pytest.importorskip("fastmcp")
        from mcp_server import curated

        summary = curated.get_url_analytics_summary(db_session, test_user, short_code="dup")

        assert summary["totals"]["clicks"] == 1
        assert sum(day["clicks"] for day in summary["daily"]) == 1

    def test_the_visits_keep_their_code(self, db_session, two_links):
        """For orphan visits and debugging; it's just not what a link's stats key on."""
        assert {visit.short_code for visit in db_session.query(Visitor).all()} == {"dup"}


class TestTheMcpCountsClicksLikeTheApp:
    """A tracking-pixel hit is an open, not a click: never counted, even with bots included."""

    @pytest.fixture
    def seen(self, db_session, test_user):
        url = URL(
            short_code="pix",
            original_url="https://example.com",
            created_by=test_user.id,
            domain_id=get_or_create_default_domain(db_session).id,
        )
        db_session.add(url)
        db_session.commit()
        _visits(db_session, url, 1, "Spain")
        _visits(db_session, url, 1, "Botland", is_bot=True)
        _visits(db_session, url, 2, "Pixelia", is_pixel=True)
        return url

    @pytest.mark.parametrize("include_bots, clicks", [(False, 1), (True, 2)])
    def test_the_same_numbers_as_the_app(
        self, client, auth_headers, db_session, test_user, seen, include_bots, clicks
    ):
        pytest.importorskip("fastmcp")
        from mcp_server import curated

        summary = curated.get_url_analytics_summary(
            db_session, test_user, short_code="pix", include_bots=include_bots
        )
        app = client.get(
            "/api/v1/analytics/urls/pix/daily",
            params={"include_bots": include_bots},
            headers=auth_headers,
        ).json()

        assert summary["totals"]["clicks"] == app["total_clicks"] == clicks
        assert sum(day["clicks"] for day in summary["daily"]) == clicks
        assert "Pixelia" not in {row["country"] for row in summary["top_countries"]}
