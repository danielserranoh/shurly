"""
`GET /api/v1/analytics/urls/{short_code}/geo` counts as the rest of a link's analytics (3.16): every
click of the period's local days, and "Unknown" for a click with no country. So its total is the
breakdown's, and the MCP's `get_url_geo_stats` agrees with `get_url_breakdown`.

`days`, its old parameter, still works: the last N days, as `period`. Past 731 it counts the last 731,
the period's longest: the cap wins.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from server.core.models import URL, Visitor
from server.utils.domain import get_or_create_default_domain

GEO = "/api/v1/analytics/urls/geo1/geo"
BREAKDOWN = "/api/v1/analytics/urls/geo1/breakdown"
NOW = datetime.now(timezone.utc).replace(tzinfo=None)
MIDNIGHT = datetime.combine(NOW.date(), time.min)  # today's, in UTC: the test user has no zone
MINUTE = timedelta(minutes=1)


@pytest.fixture
def link(db_session, test_user) -> URL:
    url = URL(
        short_code="geo1",
        original_url="https://example.com",
        created_by=test_user.id,
        domain_id=get_or_create_default_domain(db_session).id,
    )
    db_session.add(url)
    db_session.commit()
    return url


def _visit(db, url: URL, at: datetime, country: str | None, *, bot=False, pixel=False) -> None:
    db.add(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip="203.0.113.0",
            country=country,
            is_bot=bot,
            is_pixel=pixel,
            visited_at=at,
        )
    )
    db.commit()


def _geo(client, headers, query: str = "") -> dict:
    response = client.get(f"{GEO}{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _countries(body: dict) -> dict[str, int]:
    return {s["country"]: s["clicks"] for s in body["stats"]}


def test_a_click_without_a_country_is_unknown(client, auth_headers, db_session, link):
    for country in ("ES", "ES", None, "FR"):
        _visit(db_session, link, NOW - MINUTE, country)

    body = _geo(client, auth_headers)

    assert [(s["country"], s["clicks"]) for s in body["stats"]] == [
        ("ES", 2),
        ("FR", 1),
        ("Unknown", 1),
    ]
    assert body["total_clicks"] == 4


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?period=7",
        "?period=1",
        f"?from={(NOW - timedelta(days=40)).date()}&to={(NOW - timedelta(days=3)).date()}",
        "?period=7&tz=Pacific/Kiritimati",
        "?tz=America/Los_Angeles",
    ],
)
def test_the_total_is_the_breakdowns(client, auth_headers, db_session, link, query):
    """The same clicks of the same local days: a minute either side of each period's first
    midnight, bots and email opens, which aren't clicks, and clicks with no country."""
    for days in (1, 7, 30):
        start = MIDNIGHT - timedelta(days=days - 1)
        _visit(db_session, link, start - MINUTE, "ES")
        _visit(db_session, link, start + MINUTE, None)
    for age in (timedelta(hours=1), timedelta(hours=30), timedelta(days=12), timedelta(days=45)):
        _visit(db_session, link, NOW - age, "FR")
    _visit(db_session, link, NOW - MINUTE, "ES", bot=True)
    _visit(db_session, link, NOW - MINUTE, "ES", pixel=True)

    geo = _geo(client, auth_headers, query)
    breakdown = client.get(f"{BREAKDOWN}{query}", headers=auth_headers).json()

    assert geo["total_clicks"] == breakdown["total"]
    assert _countries(geo) == {item["name"]: item["count"] for item in breakdown["countries"]}


def test_the_period_is_local_days_not_the_last_hours(client, auth_headers, db_session, link):
    """Seven days start at the local midnight six days ago: a click a minute before it is out,
    though it's less than 7 × 24 hours old."""
    _visit(db_session, link, MIDNIGHT - timedelta(days=6) - MINUTE, "ES")
    _visit(db_session, link, MIDNIGHT - timedelta(days=6) + MINUTE, "FR")

    body = _geo(client, auth_headers, "?period=7")

    assert (_countries(body), body["period_days"]) == ({"FR": 1}, 7)


def test_days_is_the_period(client, auth_headers, db_session, link):
    _visit(db_session, link, MIDNIGHT - timedelta(days=6) - MINUTE, "ES")
    _visit(db_session, link, NOW - MINUTE, "FR")

    old, new = _geo(client, auth_headers, "?days=7"), _geo(client, auth_headers, "?period=7")

    assert old == new
    assert (old["period_days"], _countries(old)) == (7, {"FR": 1})


def test_days_past_the_periods_longest_counts_the_last_731(client, auth_headers, db_session, link):
    _visit(db_session, link, NOW - timedelta(days=700), "ES")
    _visit(db_session, link, NOW - timedelta(days=800), "FR")

    body = _geo(client, auth_headers, "?days=3660")

    assert (body["period_days"], _countries(body)) == (731, {"ES": 1})


@pytest.mark.parametrize("query", ["?days=7&period=7", "?days=7&from=2026-01-01&to=2026-01-02"])
def test_days_and_a_period_both_is_a_422(client, auth_headers, link, query):
    response = client.get(f"{GEO}{query}", headers=auth_headers)

    assert response.status_code == 422
    assert "days" in response.text


def test_the_csv_counts_unknown_too(client, auth_headers, db_session, link):
    for country in ("ES", None, None):
        _visit(db_session, link, NOW - MINUTE, country)

    response = client.get(f"{GEO}?format=csv", headers=auth_headers)

    lines = response.text.strip().splitlines()
    assert lines[0].lstrip("﻿").strip() == "country,clicks"
    assert {tuple(line.strip().split(",")) for line in lines[1:]} == {("Unknown", "2"), ("ES", "1")}
