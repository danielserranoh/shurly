"""
Phase 3.16 — a link's visits, as on Shlink's link page (ROADMAP 3.16.1): the list, a page at a
time and newest first, and its CSV, every visit of the period. The list never shows an IP, a
user agent or a full referrer; the CSV adds the raw user agent, and still no IP.

"Now" is frozen at 2026-10-26 10:00 UTC.
"""

import csv
import io
from datetime import datetime, timedelta

import pytest

from server.core.models import URL, User
from server.utils import local_days
from server.utils.domain import get_or_create_default_domain
from tests.test_phase316_link_analytics import (
    CURL,
    IPHONE_SAFARI,
    NOW,
    WINDOWS_CHROME,
    _utc,
    _visit,
)

IP = "203.0.113.0"  # what `_visit` stores: it must never come out


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


def _list(client, auth_headers, **params):
    return client.get("/api/v1/analytics/urls/ia-bcn/visits", params=params, headers=auth_headers)


def _csv(client, auth_headers, **params):
    return client.get(
        "/api/v1/analytics/urls/ia-bcn/visits.csv", params=params, headers=auth_headers
    )


def _rows(response) -> list[dict]:
    return list(csv.DictReader(io.StringIO(response.text)))


@pytest.fixture
def visits(db_session, link):
    _visit(
        db_session,
        link,
        _utc(2026, 10, 25, 21, 54, 12, 345678),
        country="ES",
        referer="https://www.linkedin.com/feed/?trk=secret",
    )
    _visit(db_session, link, _utc(2026, 10, 24, 9), user_agent=IPHONE_SAFARI, country=None)
    _visit(db_session, link, _utc(2026, 10, 25, 8), is_pixel=True, user_agent=IPHONE_SAFARI)
    _visit(db_session, link, _utc(2026, 10, 26, 9), is_bot=True, user_agent=CURL, country="US")
    # A bot that fetched the pixel: a bot's visit, not an open.
    _visit(db_session, link, _utc(2026, 10, 23, 9), is_pixel=True, is_bot=True, user_agent=CURL)
    _visit(db_session, link, _utc(2026, 10, 20, 12), country="FR", referer="")
    _visit(db_session, link, _utc(2026, 9, 1, 12), country="DE")  # before the period


class TestList:
    def test_the_clicks_newest_first(self, client, auth_headers, visits):
        body = _list(client, auth_headers, period=7, tz="Europe/Madrid").json()

        assert (body["type"], body["total"], body["page"], body["page_size"], body["pages"]) == (
            "clicks",
            3,
            1,
            20,
            1,
        )
        assert (body["from"], body["to"], body["timezone"]) == (
            "2026-10-20",
            "2026-10-26",
            "Europe/Madrid",
        )
        assert body["visits"] == [
            {
                "visited_at": "2026-10-25T22:54:12+01:00",  # local, to the second
                "kind": "click",
                "country": "ES",
                "browser": "Chrome",
                "os": "Windows",
                "device": "desktop",
                "referrer": "www.linkedin.com",  # never the path or query
            },
            {
                "visited_at": "2026-10-24T11:00:00+02:00",
                "kind": "click",
                "country": "Unknown",
                "browser": "Safari",
                "os": "iOS",
                "device": "mobile",
                "referrer": "Direct",
            },
            {
                "visited_at": "2026-10-20T14:00:00+02:00",
                "kind": "click",
                "country": "FR",
                "browser": "Chrome",
                "os": "Windows",
                "device": "desktop",
                "referrer": "Direct",
            },
        ]

    def test_nothing_that_identifies_a_visitor(self, client, auth_headers, visits):
        response = _list(client, auth_headers, type="all")

        assert IP not in response.text
        assert WINDOWS_CHROME not in response.text and "Mozilla" not in response.text
        assert "trk=secret" not in response.text

    @pytest.mark.parametrize(
        "kind, expected",
        [
            ("opens", ["open"]),
            ("bots", ["bot", "bot"]),
            ("all", ["bot", "click", "open", "click", "bot", "click"]),
        ],
    )
    def test_by_kind(self, client, auth_headers, visits, kind, expected):
        body = _list(client, auth_headers, type=kind).json()

        assert [visit["kind"] for visit in body["visits"]] == expected
        assert body["total"] == len(expected)

    def test_a_page_at_a_time(self, client, db_session, auth_headers, link):
        start = _utc(2026, 10, 25, 12)
        for minute in range(25):
            _visit(
                db_session,
                link,
                start - timedelta(minutes=minute),
                referer=f"https://r{minute}.example/",
            )

        first = _list(client, auth_headers).json()
        second = _list(client, auth_headers, page=2).json()
        past = _list(client, auth_headers, page=3)

        assert (first["total"], first["pages"], len(first["visits"])) == (25, 2, 20)
        assert [v["referrer"] for v in second["visits"]] == [f"r{m}.example" for m in range(20, 25)]
        assert (past.status_code, past.json()["visits"], past.json()["total"]) == (200, [], 25)

    def test_the_same_moment_pages_without_repeats(self, client, db_session, auth_headers, link):
        """Visits at the same instant keep one order across pages."""
        for n in range(30):
            _visit(db_session, link, _utc(2026, 10, 25, 12), referer=f"https://r{n}.example/")

        seen = []
        for page in range(1, 6):
            body = _list(client, auth_headers, page=page, page_size=7).json()
            seen += [visit["referrer"] for visit in body["visits"]]

        assert sorted(seen) == sorted(f"r{n}.example" for n in range(30))

    @pytest.mark.parametrize(
        "params", [{"page": 0}, {"page_size": 0}, {"page_size": 101}, {"type": "pixels"}]
    )
    def test_what_it_refuses(self, client, auth_headers, link, params):
        assert _list(client, auth_headers, **params).status_code == 422

    def test_nothing_yet(self, client, auth_headers, link):
        body = _list(client, auth_headers).json()

        assert (body["total"], body["pages"], body["visits"]) == (0, 0, [])


class TestCsv:
    def test_every_visit_of_the_period_with_its_user_agent(self, client, auth_headers, visits):
        response = _csv(client, auth_headers, period=7, tz="Europe/Madrid")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert (
            'filename="ia-bcn-visits-2026-10-20-2026-10-26.csv"'
            in response.headers["content-disposition"]
        )
        rows = _rows(response)
        assert list(rows[0]) == [
            "visited_at",
            "kind",
            "country",
            "browser",
            "os",
            "device",
            "referrer",
            "user_agent",
        ]
        assert [(r["visited_at"], r["kind"], r["country"]) for r in rows] == [
            ("2026-10-26T10:00:00+01:00", "bot", "US"),
            ("2026-10-25T22:54:12+01:00", "click", "ES"),
            ("2026-10-25T09:00:00+01:00", "open", "Unknown"),
            ("2026-10-24T11:00:00+02:00", "click", "Unknown"),
            ("2026-10-23T11:00:00+02:00", "bot", "Unknown"),
            ("2026-10-20T14:00:00+02:00", "click", "FR"),
        ]
        assert rows[0]["user_agent"] == CURL and rows[0]["browser"] == "Bot"
        assert rows[1]["referrer"] == "www.linkedin.com"

    def test_never_an_ip(self, client, auth_headers, visits):
        assert IP not in _csv(client, auth_headers, type="all").text

    def test_only_a_kind(self, client, auth_headers, visits):
        rows = _rows(_csv(client, auth_headers, period=7, type="clicks"))

        assert [row["kind"] for row in rows] == ["click", "click", "click"]

    def test_every_cell_is_spreadsheet_safe(self, client, db_session, auth_headers, link):
        """A user agent comes from anyone: one that starts like a formula stays text."""
        _visit(db_session, link, _utc(2026, 10, 25, 12), user_agent='=HYPERLINK("https://x.test")')

        (row,) = _rows(_csv(client, auth_headers))

        assert row["user_agent"] == '\'=HYPERLINK("https://x.test")'

    def test_the_period_rules_hold(self, client, auth_headers, link):
        assert _csv(client, auth_headers, **{"from": "2026-10-01"}).status_code == 422


class TestScope:
    def test_only_what_the_viewer_can_see(self, client, db_session, auth_headers):
        someone = User(email="someone@griddo.io", password_hash="x", is_active=True)
        db_session.add(someone)
        db_session.flush()
        db_session.add(
            URL(short_code="theirs", original_url="https://e.com", created_by=someone.id)
        )
        db_session.commit()

        for route in ("visits", "visits.csv"):
            url = f"/api/v1/analytics/urls/theirs/{route}"
            assert client.get(url, headers=auth_headers).status_code == 404


def test_the_period_is_local_days(client, db_session, auth_headers, link):
    """Madrid's day starts at 22:00 UTC the day before, in October's summer time."""
    _visit(db_session, link, datetime(2026, 10, 19, 21, 59, tzinfo=NOW.tzinfo))
    _visit(db_session, link, datetime(2026, 10, 19, 22, 0, tzinfo=NOW.tzinfo))

    body = _list(client, auth_headers, period=7, tz="Europe/Madrid").json()

    assert [visit["visited_at"] for visit in body["visits"]] == ["2026-10-20T00:00:00+02:00"]
