"""
Phase 3.16 — per-link analytics, as on Shlink's link page (ROADMAP 3.16.1): the header's
all-time totals, the series by day, week or month with the hours and weekdays, and the
breakdown by OS, browser, device, referrer and country, for a period.

Every visit is one kind: a click (what every other count calls one), an email open (a pixel
hit that isn't a bot's) or a bot's. Missing values have labels: "Unknown", and "Direct" for
no referrer.

"Now" is frozen at 2026-10-26 10:00 UTC, the Monday after Europe/Madrid's clocks went back
(Sunday 2026-10-25 lasted 25 hours there).
"""

import asyncio
from datetime import datetime, timezone

import pytest

from server.core.models import URL, User, UserProfile, Visitor
from server.utils import local_days
from server.utils.domain import get_or_create_default_domain

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=timezone.utc)
UTC = timezone.utc

WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Safari/537.36"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
IPAD_SAFARI = (
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)
MAC_SAFARI = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Safari/605.1.15"
)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/129.0.0.0 Mobile Safari/537.36"
)
CURL = "curl/8.7.1"


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(local_days, "_now", lambda: NOW)


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="ia-bcn",
        original_url="https://example.com",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _visit(db, url, at: datetime, **fields) -> None:
    """A visit at `at` (aware): a click unless `is_pixel` or `is_bot` say otherwise."""
    fields.setdefault("user_agent", WINDOWS_CHROME)
    db.add(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip="203.0.113.0",
            visited_at=at.astimezone(UTC).replace(tzinfo=None),
            **fields,
        )
    )
    db.commit()


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _get(client, auth_headers, route: str, **params):
    return client.get(f"/api/v1/analytics/urls/ia-bcn/{route}", params=params, headers=auth_headers)


def _items(dimension: list[dict]) -> list[tuple[str, int]]:
    return [(item["name"], item["count"]) for item in dimension]


class TestPeriod:
    """Every route but /totals takes `period`, or `from` and `to`, and says what it counted."""

    def test_the_last_30_days_by_default(self, client, auth_headers, link):
        body = _get(client, auth_headers, "timeseries").json()

        assert (body["from"], body["to"], body["timezone"]) == (
            "2026-09-27",
            "2026-10-26",
            "Etc/UTC",
        )
        assert (body["short_code"], body["domain"]) == ("ia-bcn", link.domain.hostname)

    def test_the_last_n_days_today_included(self, client, auth_headers, link):
        body = _get(client, auth_headers, "breakdown", period=7).json()

        assert (body["from"], body["to"]) == ("2026-10-20", "2026-10-26")

    def test_a_custom_range_ends_today_at_the_latest(self, client, auth_headers, link):
        body = _get(
            client, auth_headers, "timeseries", **{"from": "2026-10-01", "to": "2027-01-31"}
        )

        assert (body.json()["from"], body.json()["to"]) == ("2026-10-01", "2026-10-26")

    def test_today_is_the_viewers(self, client, auth_headers, link):
        """At 10:00 UTC on the 26th, it's midnight on the 27th in Kiritimati (UTC+14)."""
        body = _get(client, auth_headers, "timeseries", period=1, tz="Pacific/Kiritimati").json()

        assert (body["from"], body["to"], body["timezone"]) == (
            "2026-10-27",
            "2026-10-27",
            "Pacific/Kiritimati",
        )

    @pytest.mark.parametrize(
        "params",
        [
            {"period": 0},
            {"period": 732},
            {"from": "2026-10-01"},
            {"to": "2026-10-01"},
            {"period": 7, "from": "2026-10-01", "to": "2026-10-07"},
            {"from": "2026-10-08", "to": "2026-10-01"},
            {"from": "2026-10-27", "to": "2026-10-30"},  # starts after today
            {"from": "2024-10-25", "to": "2026-10-26"},  # 732 days: 731 is the most
            {"from": "not-a-date", "to": "2026-10-01"},
            {"tz": "Mars/Olympus_Mons"},
        ],
    )
    @pytest.mark.parametrize("route", ["timeseries", "breakdown"])
    def test_what_it_refuses(self, client, auth_headers, link, route, params):
        assert _get(client, auth_headers, route, **params).status_code == 422

    def test_two_years_is_fine(self, client, auth_headers, link):
        body = _get(
            client, auth_headers, "timeseries", **{"from": "2024-10-26", "to": "2026-10-26"}
        )

        assert body.status_code == 200

    def test_only_what_the_viewer_can_see(self, client, db_session, auth_headers):
        someone = User(email="someone@griddo.io", password_hash="x", is_active=True)
        db_session.add(someone)
        db_session.flush()
        db_session.add(
            URL(short_code="theirs", original_url="https://e.com", created_by=someone.id)
        )
        db_session.commit()

        for route in ("totals", "timeseries", "breakdown"):
            url = f"/api/v1/analytics/urls/theirs/{route}"
            assert client.get(url, headers=auth_headers).status_code == 404


class TestTotals:
    def test_the_headers_all_time_numbers(self, client, db_session, auth_headers, link):
        _visit(db_session, link, _utc(2025, 1, 5, 9), country="ES")
        _visit(db_session, link, _utc(2026, 10, 20, 8, 15), country="FR")
        _visit(db_session, link, _utc(2026, 10, 1, 12), country=None)
        _visit(db_session, link, _utc(2026, 10, 21, 9, 0, 0, 123456), country="ES")
        _visit(db_session, link, _utc(2026, 10, 25, 9), country="DE", is_bot=True, user_agent=CURL)
        _visit(db_session, link, _utc(2026, 10, 24, 9), is_pixel=True)
        _visit(db_session, link, _utc(2026, 10, 25, 7), is_pixel=True)
        _visit(db_session, link, _utc(2026, 10, 25, 8), is_pixel=True, is_bot=True)

        body = _get(client, auth_headers, "totals", tz="Europe/Madrid").json()

        assert body == {
            "short_code": "ia-bcn",
            "domain": link.domain.hostname,
            "timezone": "Europe/Madrid",
            "clicks": 4,
            "opens": 2,
            "countries": 2,  # ES and FR: neither the bot's DE nor the one without a country
            "last_click_at": "2026-10-21T11:00:00+02:00",  # not the later bot's, nor an open
        }

    def test_nothing_yet(self, client, auth_headers, link):
        body = _get(client, auth_headers, "totals").json()

        assert (body["clicks"], body["opens"], body["countries"], body["last_click_at"]) == (
            0,
            0,
            0,
            None,
        )

    def test_the_profiles_zone(self, client, db_session, auth_headers, link, test_user):
        db_session.add(UserProfile(user_id=test_user.id, timezone="America/New_York"))
        db_session.commit()
        _visit(db_session, link, _utc(2026, 10, 26, 3, 30))

        body = _get(client, auth_headers, "totals").json()

        assert (body["timezone"], body["last_click_at"]) == (
            "America/New_York",
            "2026-10-25T23:30:00-04:00",
        )


class TestTimeseries:
    def test_clicks_and_opens_by_day_with_zeros(self, client, db_session, auth_headers, link):
        _visit(db_session, link, _utc(2026, 10, 20, 9))
        _visit(db_session, link, _utc(2026, 10, 20, 17))
        _visit(db_session, link, _utc(2026, 10, 22, 9), is_pixel=True)
        _visit(db_session, link, _utc(2026, 10, 26, 9, 59))
        _visit(db_session, link, _utc(2026, 10, 23, 9), is_bot=True, user_agent=CURL)
        _visit(db_session, link, _utc(2026, 10, 23, 9), is_pixel=True, is_bot=True)
        _visit(db_session, link, _utc(2026, 10, 19, 23, 59))  # the day before the period

        body = _get(client, auth_headers, "timeseries", period=7).json()

        assert body["group_by"] == "day"
        assert [(s["start"], s["end"], s["clicks"], s["opens"]) for s in body["stats"]] == [
            ("2026-10-20", "2026-10-20", 2, 0),
            ("2026-10-21", "2026-10-21", 0, 0),
            ("2026-10-22", "2026-10-22", 0, 1),
            ("2026-10-23", "2026-10-23", 0, 0),
            ("2026-10-24", "2026-10-24", 0, 0),
            ("2026-10-25", "2026-10-25", 0, 0),
            ("2026-10-26", "2026-10-26", 1, 0),
        ]
        assert (body["clicks"], body["opens"]) == (3, 1)

    def test_weeks_from_monday_clipped_to_the_range(self, client, db_session, auth_headers, link):
        _visit(db_session, link, _utc(2026, 10, 1, 9))
        _visit(db_session, link, _utc(2026, 10, 11, 9))
        _visit(db_session, link, _utc(2026, 10, 12, 9), is_pixel=True)
        _visit(db_session, link, _utc(2026, 10, 26, 9))

        body = _get(
            client,
            auth_headers,
            "timeseries",
            group_by="week",
            **{"from": "2026-10-01", "to": "2026-10-26"},
        ).json()

        assert [(s["start"], s["end"], s["clicks"], s["opens"]) for s in body["stats"]] == [
            ("2026-10-01", "2026-10-04", 1, 0),  # from a Thursday
            ("2026-10-05", "2026-10-11", 1, 0),
            ("2026-10-12", "2026-10-18", 0, 1),
            ("2026-10-19", "2026-10-25", 0, 0),
            ("2026-10-26", "2026-10-26", 1, 0),  # to today, a Monday
        ]

    def test_months_clipped_to_the_range(self, client, db_session, auth_headers, link):
        _visit(db_session, link, _utc(2026, 8, 31, 12))
        _visit(db_session, link, _utc(2026, 9, 1, 12))
        _visit(db_session, link, _utc(2026, 12, 1, 12))  # after today: not in the range

        body = _get(
            client,
            auth_headers,
            "timeseries",
            group_by="month",
            **{"from": "2026-08-15", "to": "2026-12-31"},
        ).json()

        assert [(s["start"], s["end"], s["clicks"]) for s in body["stats"]] == [
            ("2026-08-15", "2026-08-31", 1),
            ("2026-09-01", "2026-09-30", 1),
            ("2026-10-01", "2026-10-26", 0),
        ]

    def test_days_are_local(self, client, db_session, auth_headers, link):
        """Asia/Kolkata's days start at 18:30 UTC."""
        _visit(db_session, link, _utc(2026, 10, 24, 18, 29))
        _visit(db_session, link, _utc(2026, 10, 24, 18, 30))

        body = _get(client, auth_headers, "timeseries", period=3, tz="Asia/Kolkata").json()

        assert [(s["start"], s["clicks"]) for s in body["stats"]] == [
            ("2026-10-24", 1),
            ("2026-10-25", 1),
            ("2026-10-26", 0),
        ]

    def test_hours_and_weekdays_are_local(self, client, db_session, auth_headers, link):
        """On the day Madrid's clocks went back, 02:30 happened twice: both count in hour 2."""
        _visit(db_session, link, _utc(2026, 10, 25, 0, 30))  # 02:30 CEST
        _visit(db_session, link, _utc(2026, 10, 25, 1, 30))  # 02:30 CET, an hour later
        _visit(db_session, link, _utc(2026, 10, 25, 23, 30), is_pixel=True)  # Monday, 00:30 CET
        _visit(db_session, link, _utc(2026, 10, 25, 9), is_bot=True, user_agent=CURL)

        body = _get(client, auth_headers, "timeseries", period=7, tz="Europe/Madrid").json()

        hours = body["hour_of_day"]
        assert [h["hour"] for h in hours] == list(range(24))
        assert {
            h["hour"]: (h["clicks"], h["opens"]) for h in hours if h["clicks"] or h["opens"]
        } == {
            0: (0, 1),
            2: (2, 0),
        }
        weekdays = body["day_of_week"]
        assert [d["day"] for d in weekdays] == [1, 2, 3, 4, 5, 6, 7]
        assert {
            d["day"]: (d["clicks"], d["opens"]) for d in weekdays if d["clicks"] or d["opens"]
        } == {
            1: (0, 1),  # Monday
            7: (2, 0),  # Sunday
        }

    def test_only_by_day_week_or_month(self, client, auth_headers, link):
        assert _get(client, auth_headers, "timeseries", group_by="hour").status_code == 422


class TestBreakdown:
    @pytest.fixture
    def visits(self, db_session, link):
        at = _utc(2026, 10, 25, 12)
        for user_agent, referer, country in [
            (WINDOWS_CHROME, "https://www.LinkedIn.com/feed/?trk=abc", "ES"),
            (WINDOWS_CHROME, "https://www.linkedin.com/", "ES"),
            (WINDOWS_CHROME, None, "FR"),
            (IPHONE_SAFARI, "", "ES"),
            (IPHONE_SAFARI, "android-app://com.linkedin.android/", None),
            (IPAD_SAFARI, "https://t.co/xyz", "ES"),
            (MAC_SAFARI, "not a url", "ES"),
            (ANDROID_CHROME, "https://www.linkedin.com/in/someone", "DE"),
            (None, None, None),
        ]:
            _visit(db_session, link, at, user_agent=user_agent, referer=referer, country=country)
        _visit(db_session, link, at, is_pixel=True, user_agent=IPHONE_SAFARI, country="PT")
        _visit(db_session, link, at, is_bot=True, user_agent=CURL, country="US")
        _visit(db_session, link, at, is_bot=True, is_pixel=True, user_agent=CURL, country="US")

    def test_every_dimension_by_count_then_name(self, client, auth_headers, visits):
        body = _get(client, auth_headers, "breakdown").json()

        assert (body["type"], body["total"]) == ("clicks", 9)
        assert _items(body["os"]) == [
            ("iOS", 3),
            ("Windows", 3),
            ("Android", 1),
            ("macOS", 1),
            ("Unknown", 1),
        ]
        assert _items(body["browsers"]) == [("Chrome", 4), ("Safari", 4), ("Unknown", 1)]
        assert _items(body["devices"]) == [
            ("desktop", 4),
            ("mobile", 3),
            ("tablet", 1),
            ("Unknown", 1),
        ]
        assert _items(body["referrers"]) == [
            ("Direct", 3),  # no referrer, or an empty one
            ("www.linkedin.com", 3),  # the host, lowercased, never the path or query
            ("com.linkedin.android", 1),  # an Android app's (android-app://)
            ("t.co", 1),
            ("Unknown", 1),  # a referrer that names no host
        ]
        assert _items(body["countries"]) == [("ES", 5), ("Unknown", 2), ("DE", 1), ("FR", 1)]

    def test_shares_add_up_to_one(self, client, auth_headers, visits):
        body = _get(client, auth_headers, "breakdown").json()

        for dimension in ("os", "browsers", "devices", "referrers", "countries"):
            items = body[dimension]
            assert all(item["share"] == round(item["count"] / 9, 4) for item in items)
            assert sum(item["share"] for item in items) == pytest.approx(1, abs=0.001)

    def test_by_kind(self, client, auth_headers, visits):
        opens = _get(client, auth_headers, "breakdown", type="opens").json()
        bots = _get(client, auth_headers, "breakdown", type="bots").json()
        every = _get(client, auth_headers, "breakdown", type="all").json()

        assert (opens["type"], opens["total"], _items(opens["countries"])) == (
            "opens",
            1,
            [("PT", 1)],
        )
        assert (bots["total"], _items(bots["browsers"]), _items(bots["devices"])) == (
            2,
            [("Bot", 2)],
            [("other", 2)],
        )
        assert every["total"] == 9 + 1 + 2

    def test_only_the_period(self, client, db_session, auth_headers, link):
        _visit(db_session, link, _utc(2026, 10, 19, 23, 59), country="ES")
        _visit(db_session, link, _utc(2026, 10, 20, 0, 0), country="FR")

        body = _get(client, auth_headers, "breakdown", period=7).json()

        assert (body["total"], _items(body["countries"])) == (1, [("FR", 1)])

    def test_nothing_in_the_period(self, client, auth_headers, link):
        body = _get(client, auth_headers, "breakdown").json()

        assert body["total"] == 0
        assert all(body[d] == [] for d in ("os", "browsers", "devices", "referrers", "countries"))

    def test_only_these_kinds(self, client, auth_headers, link):
        assert _get(client, auth_headers, "breakdown", type="pixels").status_code == 422


class TestKinds:
    """Every visit is exactly one kind, whichever route counts it."""

    def test_the_four_flag_combinations(self, client, db_session, auth_headers, link):
        at = _utc(2026, 10, 25, 12)
        for is_pixel in (False, True):
            for is_bot in (False, True):
                _visit(db_session, link, at, is_pixel=is_pixel, is_bot=is_bot)

        totals = {
            kind: _get(client, auth_headers, "breakdown", type=kind).json()["total"]
            for kind in ("clicks", "opens", "bots", "all")
        }
        series = _get(client, auth_headers, "timeseries", period=7).json()
        header = _get(client, auth_headers, "totals").json()

        assert totals == {"clicks": 1, "opens": 1, "bots": 2, "all": 4}
        assert (series["clicks"], series["opens"]) == (1, 1)
        assert (header["clicks"], header["opens"]) == (1, 1)


class TestThroughTheMcp:
    def test_a_custom_range(self, db_session, test_user, link):
        """`from` is a keyword in Python, not in a tool's arguments."""
        pytest.importorskip("fastmcp")
        from main import app
        from mcp_server.server import build_mcp_for_app
        from server.core import get_db
        from tests.test_phase54_mcp_auth import _bound_access_token

        _visit(db_session, link, _utc(2026, 10, 5, 12))
        test_user.set_api_key("analytics-key")
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with _bound_access_token("analytics-key"):
                arguments = {"short_code": "ia-bcn", "from": "2026-10-01", "to": "2026-10-07"}
                result = asyncio.run(
                    build_mcp_for_app(app).call_tool("get_url_timeseries", arguments)
                )
        finally:
            app.dependency_overrides.pop(get_db, None)

        body = result.structured_content
        assert (body["from"], body["to"], body["clicks"]) == ("2026-10-01", "2026-10-07", 1)
