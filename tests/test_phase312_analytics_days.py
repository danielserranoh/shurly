"""
Analytics days in the viewer's time zone (after Phase 3.12's profile).

A day is a calendar day where the viewer is: `?tz=` when given, else their profile's time
zone, else UTC. Its bounds are the local midnights, as naive UTC (server/utils/local_days.py),
so a day can last 23 or 25 hours, or start at 18:30 UTC. `tz` changes only how visits are
grouped into days, never which visits count.

"Now" is frozen at 2026-10-26 10:00 UTC, the Monday after Europe/Madrid's clocks went back
(Sunday 2026-10-25 lasted 25 hours there).
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from server.core.auth import hash_password
from server.core.models import URL, Campaign, URLType, User, UserProfile, Visitor
from server.utils import local_days
from server.utils.domain import get_or_create_default_domain
from server.utils.local_days import LocalDays

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
UTC = timezone.utc


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(local_days, "_now", lambda: NOW)


def _zone(db, user, name: str | None):
    db.add(UserProfile(user_id=user.id, timezone=name))
    db.commit()


def _link(db, user, code="tz1", **fields) -> URL:
    url = URL(
        short_code=code,
        original_url="https://example.com",
        created_by=user.id,
        domain_id=get_or_create_default_domain(db).id,
        **fields,
    )
    db.add(url)
    db.commit()
    return url


def _visit(db, url, at: datetime, **flags):
    db.add(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip="203.0.113.0",
            visited_at=at.astimezone(UTC).replace(tzinfo=None),
            **flags,
        )
    )
    db.commit()


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _days(response) -> dict[str, int]:
    return {row["date"]: row["clicks"] for row in response.json()["stats"]}


class TestLocalDays:
    def test_bounds_are_local_midnights_as_naive_utc(self):
        bounds = LocalDays.named("Europe/Madrid").bounds(date(2026, 7, 1), 1)

        assert bounds == [datetime(2026, 6, 30, 22, 0), datetime(2026, 7, 1, 22, 0)]
        assert all(bound.tzinfo is None for bound in bounds)

    @pytest.mark.parametrize(
        "day, hours",
        [
            (date(2026, 3, 29), 23),  # clocks go forward
            (date(2026, 10, 25), 25),  # clocks go back
            (date(2026, 10, 26), 24),
        ],
    )
    def test_a_dst_day_lasts_what_it_lasts(self, day, hours):
        start, end = LocalDays.named("Europe/Madrid").bounds(day, 1)

        assert end - start == timedelta(hours=hours)

    @pytest.mark.parametrize(
        "zone, starts_at",
        [
            ("Asia/Kolkata", datetime(2026, 10, 22, 18, 30)),  # +05:30
            ("America/Los_Angeles", datetime(2026, 10, 23, 7, 0)),  # PDT, −07:00
            ("Etc/UTC", datetime(2026, 10, 23, 0, 0)),
        ],
    )
    def test_a_day_starts_at_its_local_midnight(self, zone, starts_at):
        assert LocalDays.named(zone).bounds(date(2026, 10, 23), 1)[0] == starts_at

    @pytest.mark.parametrize("zone", ["America/Santiago", "America/Havana", "Europe/Madrid"])
    def test_zones_whose_clocks_change_at_midnight_still_give_ordered_days(self, zone):
        bounds = LocalDays.named(zone).bounds(date(2026, 1, 1), 365)

        lengths = {end - start for start, end in zip(bounds, bounds[1:], strict=False)}
        assert lengths <= {timedelta(hours=23), timedelta(hours=24), timedelta(hours=25)}

    @pytest.mark.parametrize(
        "zone, today",
        [
            ("Etc/UTC", date(2026, 10, 26)),
            ("Pacific/Kiritimati", date(2026, 10, 27)),  # +14:00
            ("Pacific/Pago_Pago", date(2026, 10, 25)),  # −11:00
        ],
    )
    def test_today_is_where_the_viewer_is(self, zone, today):
        assert LocalDays.named(zone).today() == today


class TestWhichZone:
    def test_utc_without_a_profile(self, client, auth_headers, db_session, test_user):
        _link(db_session, test_user)

        response = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)

        assert response.json()["timezone"] == "Etc/UTC"

    def test_the_profiles(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Atlantic/Canary")
        _link(db_session, test_user)

        response = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)

        assert response.json()["timezone"] == "Atlantic/Canary"

    def test_tz_wins_and_takes_the_profiles_rules(
        self, client, auth_headers, db_session, test_user
    ):
        _zone(db_session, test_user, "Atlantic/Canary")
        _link(db_session, test_user)

        response = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"tz": "asia/calcutta"}, headers=auth_headers
        )

        assert response.json()["timezone"] == "Asia/Kolkata"

    @pytest.mark.parametrize("tz", ["+02:00", "Mars/Olympus_Mons"])
    def test_a_tz_that_isnt_one_is_a_422(self, client, auth_headers, db_session, test_user, tz):
        _link(db_session, test_user)

        response = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"tz": tz}, headers=auth_headers
        )

        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", "tz"]
        assert "IANA" in response.json()["detail"][0]["msg"]

    def test_tz_never_shows_more(self, client, auth_headers, db_session, test_user):
        """Someone else's personal link stays a 404, whatever the zone."""
        other = User(email="other@example.com", password_hash=hash_password("other-pass-1"))
        db_session.add(other)
        db_session.commit()
        _link(db_session, other, code="theirs")

        for path in ("daily", "weekly"):
            response = client.get(
                f"/api/v1/analytics/urls/theirs/{path}",
                params={"tz": "Asia/Kolkata"},
                headers=auth_headers,
            )
            assert response.status_code == 404


class TestDaily:
    def test_counts_each_day_exactly(self, client, auth_headers, db_session, test_user):
        """The per-day counts, which tests on SQLite never saw before (they read 0)."""
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 19, 23, 59, 59))  # the day before the 7
        _visit(db_session, url, _utc(2026, 10, 20, 0, 0, 0))  # first second of the first
        for minute in range(3):
            _visit(db_session, url, _utc(2026, 10, 23, 12, minute))
        _visit(db_session, url, _utc(2026, 10, 26, 9, 59))

        response = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)

        assert _days(response) == {
            "2026-10-20": 1,
            "2026-10-21": 0,
            "2026-10-22": 0,
            "2026-10-23": 3,
            "2026-10-24": 0,
            "2026-10-25": 0,
            "2026-10-26": 1,
        }
        assert response.json()["total_clicks"] == 5

    def test_in_madrid_around_its_25_hour_day(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Europe/Madrid")
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 24, 22, 30))  # 00:30 CEST on the 25th
        _visit(db_session, url, _utc(2026, 10, 25, 22, 30))  # 23:30 CET, still the 25th
        _visit(db_session, url, _utc(2026, 10, 25, 23, 30))  # 00:30 CET on the 26th

        madrid = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)
        in_utc = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"tz": "UTC"}, headers=auth_headers
        )

        assert (_days(madrid)["2026-10-25"], _days(madrid)["2026-10-26"]) == (2, 1)
        assert (_days(in_utc)["2026-10-24"], _days(in_utc)["2026-10-25"]) == (1, 2)
        assert madrid.json()["total_clicks"] == in_utc.json()["total_clicks"] == 3

    @pytest.mark.parametrize(
        "zone, at, local_day",
        [
            ("Asia/Kolkata", _utc(2026, 10, 22, 18, 40), "2026-10-23"),  # 00:10 IST
            ("America/Los_Angeles", _utc(2026, 10, 26, 3, 0), "2026-10-25"),  # 20:00 PDT
        ],
    )
    def test_a_visit_lands_on_its_local_day(
        self, client, auth_headers, db_session, test_user, zone, at, local_day
    ):
        url = _link(db_session, test_user)
        _visit(db_session, url, at)

        response = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"tz": zone}, headers=auth_headers
        )

        assert {day for day, clicks in _days(response).items() if clicks} == {local_day}

    def test_bots_and_pixels_still_left_out(self, client, auth_headers, db_session, test_user):
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 26, 8, 0))
        _visit(db_session, url, _utc(2026, 10, 26, 8, 1), is_bot=True)
        _visit(db_session, url, _utc(2026, 10, 26, 8, 2), is_pixel=True)

        people = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)
        with_bots = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"include_bots": True}, headers=auth_headers
        )

        assert _days(people)["2026-10-26"] == 1
        assert _days(with_bots)["2026-10-26"] == 2  # a pixel is never a click

    def test_the_csv_has_the_local_days(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Europe/Madrid")
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 24, 22, 30))  # the 25th in Madrid

        response = client.get(
            "/api/v1/analytics/urls/tz1/daily", params={"format": "csv"}, headers=auth_headers
        )

        assert "2026-10-25,1" in response.text.splitlines()

    def test_one_query_bounded_by_the_whole_range(
        self, client, auth_headers, db_session, test_user
    ):
        """The range filters the visits before the per-day sums, so an index on
        visited_at can narrow the scan."""
        _link(db_session, test_user)
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", record)
        try:
            client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)
        finally:
            event.remove(engine, "before_cursor_execute", record)

        counting = [s for s in statements if "CASE" in s and "visits" in s]
        assert len(counting) == 1
        where = counting[0].split("WHERE", 1)[1]
        assert "visits.visited_at >=" in where and "visits.visited_at <" in where


class TestWeekly:
    def test_eight_weeks_ending_today(self, client, auth_headers, db_session, test_user):
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 8, 31, 23, 59))  # before the first week
        _visit(db_session, url, _utc(2026, 9, 1, 0, 0))  # first moment of the first
        _visit(db_session, url, NOW - timedelta(hours=1))  # today

        response = client.get("/api/v1/analytics/urls/tz1/weekly", headers=auth_headers)

        weeks = response.json()["stats"]
        assert len(weeks) == 8
        assert (weeks[0]["week_start"], weeks[0]["week_end"]) == ("2026-09-01", "2026-09-07")
        assert (weeks[-1]["week_start"], weeks[-1]["week_end"]) == ("2026-10-20", "2026-10-26")
        assert [week["clicks"] for week in weeks] == [1, 0, 0, 0, 0, 0, 0, 1]
        assert response.json()["timezone"] == "Etc/UTC"

    def test_in_the_viewers_zone(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Pacific/Kiritimati")  # +14: already the 27th there
        url = _link(db_session, test_user)
        _visit(db_session, url, NOW)

        response = client.get("/api/v1/analytics/urls/tz1/weekly", headers=auth_headers)

        last = response.json()["stats"][-1]
        assert (last["week_end"], last["clicks"]) == ("2026-10-27", 1)


class TestOverview:
    def test_the_headline_is_the_charts_sum(self, client, auth_headers, db_session, test_user):
        """Changed: 7 local calendar days including today, where it was a rolling 168 hours."""
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 19, 12, 0))  # within 168 h, before the 7 days
        _visit(db_session, url, _utc(2026, 10, 21, 12, 0))
        _visit(db_session, url, _utc(2026, 10, 26, 9, 0))

        data = client.get("/api/v1/analytics/overview", headers=auth_headers).json()

        assert data["recent_clicks_7d"] == 2
        assert sum(day["clicks"] for day in data["recent_activity"]) == 2
        assert data["recent_activity"][-1] == {"date": "2026-10-26", "clicks": 1}
        assert data["timezone"] == "Etc/UTC"

    def test_in_the_viewers_zone(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Europe/Madrid")
        url = _link(db_session, test_user)
        _visit(db_session, url, _utc(2026, 10, 25, 23, 30))  # the 26th in Madrid

        data = client.get("/api/v1/analytics/overview", headers=auth_headers).json()

        assert data["recent_activity"][-1] == {"date": "2026-10-26", "clicks": 1}
        assert data["timezone"] == "Europe/Madrid"


class TestCampaignSummary:
    def test_the_timeline_in_the_viewers_zone(self, client, auth_headers, db_session, test_user):
        _zone(db_session, test_user, "Asia/Kolkata")
        campaign = Campaign(
            name="Q4",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()
        url = _link(
            db_session,
            test_user,
            code="q4ana",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"name": "Ana"},
        )
        _visit(db_session, url, _utc(2026, 10, 22, 18, 40))  # the 23rd in Kolkata

        data = client.get(
            f"/api/v1/analytics/campaigns/{campaign.id}/summary", headers=auth_headers
        ).json()

        clicked = [day["date"] for day in data["daily_timeline"] if day["clicks"]]
        assert clicked == ["2026-10-23"]
        assert data["timezone"] == "Asia/Kolkata"


class TestTheMcpSummary:
    def test_gives_the_apps_numbers(self, client, auth_headers, db_session, test_user):
        pytest.importorskip("fastmcp")
        from mcp_server import curated

        _zone(db_session, test_user, "Europe/Madrid")
        url = _link(db_session, test_user)
        for at in (
            _utc(2026, 10, 24, 22, 30),
            _utc(2026, 10, 25, 22, 30),
            _utc(2026, 10, 25, 23, 30),
        ):
            _visit(db_session, url, at)

        summary = curated.get_url_analytics_summary(db_session, test_user, short_code="tz1")
        app = client.get("/api/v1/analytics/urls/tz1/daily", headers=auth_headers)

        assert {row["date"]: row["clicks"] for row in summary["daily"]} == _days(app)
        assert summary["timezone"] == "Europe/Madrid"
