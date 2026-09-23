"""
Pagination bounds and constant SQL query counts for multi-row endpoints.

* `GET /api/v1/urls` and `GET /api/v1/campaigns` enforce the page size they
  document: `limit` must be 1-100 and `skip` >= 0, anything else is a 422.
* Endpoints that return or update many URLs run the same number of SQL
  statements whatever the row count (no N+1 queries):
  - `GET /api/v1/urls` loads the page's tags in one query;
  - `GET /api/v1/campaigns` loads the page's tags and URL counts in one query each;
  - `POST /api/v1/urls/bulk/tags` and `PATCH /api/v1/campaigns/{id}/tags` load
    the URLs' current tags in one query;
  - `GET /api/v1/analytics/campaigns/{id}/users` aggregates visits in one query.

Query counts are compared between a small and a large data set rather than
pinned to a number, so unrelated changes (e.g. auth) don't break these tests.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import event
from sqlalchemy.orm import Session

from server.core.models import URL, Campaign, Tag, URLType, User, Visitor
from server.utils.domain import get_or_create_default_domain

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _capture_statements(db: Session) -> Iterator[list[str]]:
    """Record every SQL statement the test engine executes inside the block."""
    statements: list[str] = []

    def _capture(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _capture)


def _request_sql(
    client: TestClient, db: Session, method: str, path: str, **kwargs
) -> tuple[Response, list[str]]:
    """
    Send one request that must succeed; return it with the SQL it executed.

    The test client shares `db` with the app, so rows loaded by the test or by an
    earlier request are still in its identity map. Expiring them first makes the
    request load everything itself, as a fresh per-request session would.
    """
    db.expire_all()
    with _capture_statements(db) as statements:
        response = client.request(method, path, **kwargs)
    assert response.status_code == 200, response.text
    return response, statements


def _make_tag(db: Session, name: str) -> Tag:
    tag = Tag(name=name, display_name=name.title(), color="blue-500")
    db.add(tag)
    db.commit()
    return tag


def _make_campaign(db: Session, user: User, name: str, *, tags: Sequence[Tag] = ()) -> Campaign:
    campaign = Campaign(
        name=name,
        original_url="https://example.com/landing",
        csv_columns=["name"],
        created_by=user.id,
        tags=list(tags),
    )
    db.add(campaign)
    db.commit()
    return campaign


def _make_urls(
    db: Session,
    user: User,
    codes: Sequence[str],
    *,
    tags: Sequence[Tag] = (),
    campaign: Campaign | None = None,
) -> list[URL]:
    """Seed URLs on the default domain in one commit, each carrying `tags`."""
    domain = get_or_create_default_domain(db)
    urls = [
        URL(
            short_code=code,
            domain_id=domain.id,
            original_url=f"https://example.com/{code}",
            url_type=URLType.CAMPAIGN if campaign else URLType.STANDARD,
            campaign_id=campaign.id if campaign else None,
            user_data={"name": code} if campaign else None,
            created_by=user.id,
            tags=list(tags),
        )
        for code in codes
    ]
    db.add_all(urls)
    db.commit()
    return urls


def _add_visit(
    db: Session, url: URL, *, ip: str, at: datetime, is_bot: bool = False, is_pixel: bool = False
) -> None:
    db.add(
        Visitor(
            url_id=url.id,
            short_code=url.short_code,
            ip=ip,
            visited_at=at,
            is_bot=is_bot,
            is_pixel=is_pixel,
        )
    )


def _tag_names(db: Session) -> dict[str, list[str]]:
    """Every URL's tag names, read back from the database."""
    db.expire_all()
    return {url.short_code: sorted(tag.name for tag in url.tags) for url in db.query(URL)}


# ---------------------------------------------------------------------------
# GET /api/v1/urls
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListURLs:
    @pytest.mark.parametrize("query", ["limit=101", "limit=5000", "limit=0", "limit=-1", "skip=-1"])
    def test_out_of_range_paging_is_422(self, client: TestClient, auth_headers: dict, query: str):
        r = client.get(f"/api/v1/urls?{query}", headers=auth_headers)

        assert r.status_code == 422
        assert r.json()["detail"][0]["loc"] == ["query", query.split("=")[0]]

    def test_pages_hold_up_to_100_urls_and_total_counts_them_all(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_urls(db_session, test_user, [f"page{i:03d}" for i in range(101)])

        first = client.get("/api/v1/urls", headers=auth_headers)
        last = client.get("/api/v1/urls?skip=100&limit=100", headers=auth_headers)

        assert first.status_code == last.status_code == 200
        assert (len(first.json()["urls"]), first.json()["total"]) == (100, 101)
        assert (len(last.json()["urls"]), last.json()["total"]) == (1, 101)

    def test_tags_for_the_whole_page_load_in_one_query(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        red, blue = _make_tag(db_session, "red"), _make_tag(db_session, "blue")
        _make_urls(db_session, test_user, ["both0"], tags=[red, blue])
        _make_urls(db_session, test_user, ["red0"], tags=[red])
        _, small = _request_sql(client, db_session, "GET", "/api/v1/urls", headers=auth_headers)

        _make_urls(db_session, test_user, ["both1", "both2"], tags=[red, blue])
        _make_urls(db_session, test_user, ["red1", "red2"], tags=[red])
        _make_urls(db_session, test_user, ["none0", "none1"])
        r, large = _request_sql(client, db_session, "GET", "/api/v1/urls", headers=auth_headers)

        assert len(large) == len(small), large
        assert sum("url_tags" in s for s in large) == 1, large
        tags = {u["short_code"]: sorted(t["name"] for t in u["tags"]) for u in r.json()["urls"]}
        assert tags == {
            **{f"both{i}": ["blue", "red"] for i in range(3)},
            **{f"red{i}": ["red"] for i in range(3)},
            "none0": [],
            "none1": [],
        }


# ---------------------------------------------------------------------------
# GET /api/v1/campaigns
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListCampaigns:
    @pytest.mark.parametrize("query", ["limit=101", "limit=0", "skip=-1"])
    def test_out_of_range_paging_is_422(self, client: TestClient, auth_headers: dict, query: str):
        r = client.get(f"/api/v1/campaigns?{query}", headers=auth_headers)

        assert r.status_code == 422
        assert r.json()["detail"][0]["loc"] == ["query", query.split("=")[0]]

    def test_limit_100_is_accepted(self, client: TestClient, auth_headers: dict):
        """The campaigns page asks for exactly `limit=100`."""
        r = client.get("/api/v1/campaigns?limit=100", headers=auth_headers)

        assert r.status_code == 200

    def test_tags_and_url_counts_load_in_one_query_each(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        vip = _make_tag(db_session, "vip")

        def seed(name: str, url_count: int, tags: Sequence[Tag]) -> None:
            campaign = _make_campaign(db_session, test_user, name, tags=tags)
            codes = [f"{name}{i}" for i in range(url_count)]
            _make_urls(db_session, test_user, codes, campaign=campaign)

        seed("spring", 1, [vip])
        seed("summer", 2, [])
        _, small = _request_sql(
            client, db_session, "GET", "/api/v1/campaigns", headers=auth_headers
        )

        seed("autumn", 3, [vip])
        seed("winter", 0, [vip])
        seed("launch", 4, [])
        r, large = _request_sql(
            client, db_session, "GET", "/api/v1/campaigns", headers=auth_headers
        )

        assert len(large) == len(small), large
        campaigns = {
            c["name"]: (c["url_count"], [t["name"] for t in c["tags"]])
            for c in r.json()["campaigns"]
        }
        assert campaigns == {
            "spring": (1, ["vip"]),
            "summer": (2, []),
            "autumn": (3, ["vip"]),
            "winter": (0, ["vip"]),
            "launch": (4, []),
        }


# ---------------------------------------------------------------------------
# Bulk tag writes
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTagWrites:
    def test_bulk_tag_loads_current_tags_in_one_query(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        old, new = _make_tag(db_session, "old"), _make_tag(db_session, "new")
        small_codes = ["a0", "a1"]
        large_codes = [f"b{i}" for i in range(6)]
        _make_urls(db_session, test_user, small_codes + large_codes, tags=[old])
        body = {"tag_ids": [str(new.id)]}

        def bulk_tag(codes: list[str]) -> list[str]:
            r, statements = _request_sql(
                client,
                db_session,
                "POST",
                "/api/v1/urls/bulk/tags",
                json={**body, "short_codes": codes},
                headers=auth_headers,
            )
            assert r.json() == {"updated": len(codes), "failed": []}
            return statements

        small, large = bulk_tag(small_codes), bulk_tag(large_codes)

        assert len(large) == len(small), large
        # Bulk tagging adds to the existing tags
        assert _tag_names(db_session) == {
            code: ["new", "old"] for code in small_codes + large_codes
        }

    def test_campaign_retag_loads_url_tags_in_one_query(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        old, new = _make_tag(db_session, "old"), _make_tag(db_session, "new")
        small_campaign = _make_campaign(db_session, test_user, "small")
        large_campaign = _make_campaign(db_session, test_user, "large")
        small_codes = ["s0", "s1"]
        large_codes = [f"l{i}" for i in range(6)]
        _make_urls(db_session, test_user, small_codes, tags=[old], campaign=small_campaign)
        _make_urls(db_session, test_user, large_codes, tags=[old], campaign=large_campaign)
        body = {"tag_ids": [str(new.id)]}

        def retag(campaign: Campaign) -> list[str]:
            path = f"/api/v1/campaigns/{campaign.id}/tags"
            _, statements = _request_sql(
                client, db_session, "PATCH", path, json=body, headers=auth_headers
            )
            return statements

        small, large = retag(small_campaign), retag(large_campaign)

        assert len(large) == len(small), large
        # Campaign tags replace the URLs' tags
        assert _tag_names(db_session) == {code: ["new"] for code in small_codes + large_codes}


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/campaigns/{id}/users
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCampaignUsers:
    def test_per_url_stats(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        campaign = _make_campaign(db_session, test_user, "launch")
        ada, alan, grace = _make_urls(
            db_session, test_user, ["ada", "alan", "grace"], campaign=campaign
        )
        t0 = datetime(2026, 9, 1, 12, 0)
        _add_visit(db_session, ada, ip="10.0.0.1", at=t0)
        _add_visit(db_session, ada, ip="10.0.0.1", at=t0 + timedelta(hours=1))
        _add_visit(db_session, ada, ip="10.0.0.2", at=t0 + timedelta(hours=2))
        # An email open is never a click, even with include_bots
        _add_visit(db_session, ada, ip="10.0.0.3", at=t0 + timedelta(hours=3), is_pixel=True)
        _add_visit(db_session, ada, ip="66.249.0.1", at=t0 + timedelta(hours=4), is_bot=True)
        _add_visit(db_session, alan, ip="10.0.0.4", at=t0)
        _add_visit(db_session, grace, ip="66.249.0.2", at=t0, is_bot=True)
        _add_visit(db_session, grace, ip="66.249.0.2", at=t0 + timedelta(hours=5), is_bot=True)
        db_session.commit()
        path = f"/api/v1/analytics/campaigns/{campaign.id}/users"

        def stats(query: str) -> list[tuple]:
            r = client.get(f"{path}{query}", headers=auth_headers)
            assert r.status_code == 200
            assert r.json()["total_users"] == 3
            return [
                (u["short_code"], u["clicks"], u["unique_ips"], u["last_clicked"])
                for u in r.json()["users"]
            ]

        assert stats("") == [
            ("ada", 3, 2, "2026-09-01T14:00:00"),
            ("alan", 1, 1, "2026-09-01T12:00:00"),
            ("grace", 0, 0, None),
        ]
        assert stats("?include_bots=true") == [
            ("ada", 4, 3, "2026-09-01T16:00:00"),
            ("grace", 2, 1, "2026-09-01T17:00:00"),
            ("alan", 1, 1, "2026-09-01T12:00:00"),
        ]

    def test_stats_come_from_one_grouped_query(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        def seed(name: str, url_count: int) -> Campaign:
            campaign = _make_campaign(db_session, test_user, name)
            codes = [f"{name}{i}" for i in range(url_count)]
            for i, url in enumerate(_make_urls(db_session, test_user, codes, campaign=campaign)):
                for _ in range(i):
                    _add_visit(db_session, url, ip=f"10.0.0.{i}", at=datetime(2026, 9, 1))
            db_session.commit()
            return campaign

        small_campaign, large_campaign = seed("small", 2), seed("large", 6)

        def users(campaign: Campaign) -> tuple[Response, list[str]]:
            path = f"/api/v1/analytics/campaigns/{campaign.id}/users"
            return _request_sql(client, db_session, "GET", path, headers=auth_headers)

        _, small = users(small_campaign)
        r, large = users(large_campaign)

        assert len(large) == len(small), large
        visit_queries = [s for s in large if "FROM visits" in s]
        assert len(visit_queries) == 1, visit_queries
        assert "GROUP BY" in visit_queries[0]
        assert [u["clicks"] for u in r.json()["users"]] == [5, 4, 3, 2, 1, 0]
