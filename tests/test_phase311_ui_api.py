"""
Phase 3.11 — backend support for the dashboard redesign.

Covers the additive API surface the new UI codes against:

* `URLResponse` gains `click_count`, `campaign_id` and `user_data`.
* `GET /api/v1/urls/{short_code}` — single-URL detail.
* `GET /api/v1/urls?q=...&url_type=...` — search + type filters.
* `POST /api/v1/urls/fetch-metadata` — live Open Graph preview before creation.
* `GET /api/v1/analytics/overview` — `top_urls[]` gains `short_url` + `title`.
* Campaign short URLs use the same host resolution as URL responses.
* The dev CORS default allows the frontend dev server on :4232.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from server.app import urls as urls_module
from server.core.config import Settings, settings
from server.core.models import URL, Campaign, Tag, URLType, User, Visitor
from server.utils.domain import get_or_create_default_domain
from server.utils.opengraph import OpenGraphMetadata
from server.utils.url import build_short_url

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_url(
    db: Session,
    user: User,
    code: str,
    *,
    original_url: str = "https://example.com",
    url_type: URLType = URLType.STANDARD,
    **extra,
) -> URL:
    """Seed a URL on the default domain (so per-domain UNIQUE checks behave)."""
    domain = get_or_create_default_domain(db)
    url = URL(
        short_code=code,
        domain_id=domain.id,
        original_url=original_url,
        url_type=url_type,
        created_by=user.id,
        **extra,
    )
    db.add(url)
    db.commit()
    db.refresh(url)
    return url


def _add_visits(db: Session, url: URL, *, humans: int = 0, bots: int = 0, pixels: int = 0) -> None:
    """Seed human clicks, bot hits and tracking-pixel opens for a URL."""
    for i in range(humans):
        db.add(Visitor(url_id=url.id, short_code=url.short_code, ip=f"10.0.0.{i}"))
    for i in range(bots):
        db.add(
            Visitor(
                url_id=url.id,
                short_code=url.short_code,
                ip=f"10.0.1.{i}",
                user_agent="Googlebot/2.1",
                is_bot=True,
            )
        )
    for i in range(pixels):
        db.add(
            Visitor(
                url_id=url.id,
                short_code=url.short_code,
                ip=f"10.0.2.{i}",
                is_pixel=True,
            )
        )
    db.commit()


def _make_other_user(db: Session) -> User:
    other = User(email="other@example.com", password_hash="hashed", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)
    return other


def _make_campaign(db: Session, user: User, name: str = "Spring") -> Campaign:
    campaign = Campaign(
        name=name,
        original_url="https://example.com/landing",
        csv_columns=["firstName"],
        created_by=user.id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def _codes(response) -> list[str]:
    return [u["short_code"] for u in response.json()["urls"]]


@pytest.fixture
def no_og_fetch(monkeypatch: pytest.MonkeyPatch):
    """Stub the OG fetcher used by URL creation so tests never hit the network."""

    async def _empty(*_args, **_kwargs):
        return OpenGraphMetadata()

    monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty)


# ---------------------------------------------------------------------------
# URLResponse — click_count / campaign_id / user_data
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestURLResponseClickCount:
    def test_list_click_count_excludes_bots_and_pixels(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        busy = _make_url(db_session, test_user, "busy01")
        _add_visits(db_session, busy, humans=3, bots=2, pixels=4)
        _make_url(db_session, test_user, "quiet1")

        r = client.get("/api/v1/urls", headers=auth_headers)

        assert r.status_code == 200
        counts = {u["short_code"]: u["click_count"] for u in r.json()["urls"]}
        assert counts == {"busy01": 3, "quiet1": 0}

    def test_list_click_counts_use_one_grouped_query(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        """No N+1: the whole page's counts come from a single aggregate over visits."""
        for i in range(5):
            url = _make_url(db_session, test_user, f"page{i}")
            _add_visits(db_session, url, humans=i)

        statements: list[str] = []

        def _capture(_conn, _cursor, statement, _params, _context, _executemany):
            statements.append(statement)

        engine = db_session.get_bind()
        event.listen(engine, "before_cursor_execute", _capture)
        try:
            r = client.get("/api/v1/urls", headers=auth_headers)
        finally:
            event.remove(engine, "before_cursor_execute", _capture)

        assert r.status_code == 200
        assert {u["short_code"]: u["click_count"] for u in r.json()["urls"]} == {
            f"page{i}": i for i in range(5)
        }
        visit_queries = [s for s in statements if "FROM visits" in s]
        assert len(visit_queries) == 1, visit_queries
        assert "GROUP BY" in visit_queries[0]

    def test_create_standard_and_custom_return_zero_click_count(
        self, client: TestClient, auth_headers: dict, no_og_fetch
    ):
        standard = client.post(
            "/api/v1/urls", json={"url": "https://example.com/a"}, headers=auth_headers
        )
        custom = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com/b", "custom_code": "fresh-one"},
            headers=auth_headers,
        )

        for r in (standard, custom):
            assert r.status_code == 201
            body = r.json()
            assert body["click_count"] == 0
            assert body["campaign_id"] is None
            assert body["user_data"] is None

    def test_update_returns_click_count(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        url = _make_url(db_session, test_user, "patchc")
        _add_visits(db_session, url, humans=2, bots=1, pixels=1)

        r = client.patch("/api/v1/urls/patchc", json={"title": "Renamed"}, headers=auth_headers)

        assert r.status_code == 200
        assert r.json()["title"] == "Renamed"
        assert r.json()["click_count"] == 2

    def test_campaign_url_exposes_campaign_id_and_user_data(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        campaign = _make_campaign(db_session, test_user)
        _make_url(
            db_session,
            test_user,
            "camp01",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"firstName": "Ada"},
        )
        _make_url(db_session, test_user, "plain1")

        r = client.get("/api/v1/urls", headers=auth_headers)

        assert r.status_code == 200
        by_code = {u["short_code"]: u for u in r.json()["urls"]}
        assert by_code["camp01"]["campaign_id"] == str(campaign.id)
        assert by_code["camp01"]["user_data"] == {"firstName": "Ada"}
        assert by_code["plain1"]["campaign_id"] is None
        assert by_code["plain1"]["user_data"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/urls/{short_code}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetURL:
    def test_get_url_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        url = _make_url(
            db_session,
            test_user,
            "detail1",
            original_url="https://example.com/detail",
            title="Detail page",
        )
        _add_visits(db_session, url, humans=4, bots=3, pixels=2)

        r = client.get("/api/v1/urls/detail1", headers=auth_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["id"] == str(url.id)
        assert body["short_code"] == "detail1"
        assert body["short_url"] == build_short_url("detail1")
        assert body["original_url"] == "https://example.com/detail"
        assert body["title"] == "Detail page"
        assert body["url_type"] == "standard"
        assert body["click_count"] == 4
        assert body["campaign_id"] is None
        assert body["user_data"] is None
        assert body["tags"] == []

    def test_get_campaign_url_includes_campaign_fields(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        campaign = _make_campaign(db_session, test_user)
        _make_url(
            db_session,
            test_user,
            "campget",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"firstName": "Grace"},
        )

        r = client.get("/api/v1/urls/campget", headers=auth_headers)

        assert r.status_code == 200
        assert r.json()["url_type"] == "campaign"
        assert r.json()["campaign_id"] == str(campaign.id)
        assert r.json()["user_data"] == {"firstName": "Grace"}

    def test_get_url_not_found(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/v1/urls/nope404", headers=auth_headers)

        assert r.status_code == 404
        assert r.json()["detail"] == "URL not found"

    def test_get_url_of_other_user_is_404(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        _make_url(db_session, _make_other_user(db_session), "theirs1")

        r = client.get("/api/v1/urls/theirs1", headers=auth_headers)

        assert r.status_code == 404
        assert r.json()["detail"] == "URL not found"

    def test_get_url_requires_auth(self, client: TestClient, db_session: Session, test_user: User):
        _make_url(db_session, test_user, "authme1")

        assert client.get("/api/v1/urls/authme1").status_code == 401

    def test_get_url_does_not_shadow_neighbour_routes(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "routes1", og_title="OG")

        listing = client.get("/api/v1/urls", headers=auth_headers)
        preview = client.get("/api/v1/urls/routes1/preview", headers=auth_headers)
        rules = client.get("/api/v1/urls/routes1/rules", headers=auth_headers)
        detail = client.get("/api/v1/urls/routes1", headers=auth_headers)

        assert listing.status_code == 200 and "urls" in listing.json()
        assert preview.status_code == 200 and preview.json()["og_title"] == "OG"
        assert "has_custom_preview" in preview.json()
        assert rules.status_code == 200 and rules.json() == []
        assert detail.status_code == 200 and detail.json()["short_code"] == "routes1"


# ---------------------------------------------------------------------------
# GET /api/v1/urls — q / url_type filters
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListURLFilters:
    def test_q_matches_title_original_url_or_short_code_case_insensitively(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "alpha1", title="Spring LAUNCH")
        _make_url(
            db_session,
            test_user,
            "beta22",
            original_url="https://shop.example.org/Launch-offer",
        )
        _make_url(db_session, test_user, "Launch3", title="Other")
        _make_url(db_session, test_user, "zzz999", title="Unrelated")

        r = client.get("/api/v1/urls?q=launch", headers=auth_headers)

        assert r.status_code == 200
        assert set(_codes(r)) == {"alpha1", "beta22", "Launch3"}
        assert r.json()["total"] == 3

    def test_q_treats_like_wildcards_literally(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "pct1", title="50% off")
        _make_url(db_session, test_user, "pct2", title="500 off")
        _make_url(db_session, test_user, "und1", title="snake_case")
        _make_url(db_session, test_user, "und2", title="snakeXcase")

        percent = client.get("/api/v1/urls", params={"q": "0%"}, headers=auth_headers)
        underscore = client.get("/api/v1/urls", params={"q": "e_c"}, headers=auth_headers)

        assert set(_codes(percent)) == {"pct1"}
        assert percent.json()["total"] == 1
        assert set(_codes(underscore)) == {"und1"}
        assert underscore.json()["total"] == 1

    def test_q_matches_slashes_in_destination(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "slash1", original_url="https://example.com/spring/sale")
        _make_url(db_session, test_user, "slash2", original_url="https://example.com/summer")

        r = client.get("/api/v1/urls", params={"q": "example.com/spring"}, headers=auth_headers)

        assert set(_codes(r)) == {"slash1"}

    def test_blank_q_is_ignored(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "blank1")
        _make_url(db_session, test_user, "blank2")

        empty = client.get("/api/v1/urls", params={"q": ""}, headers=auth_headers)
        spaces = client.get("/api/v1/urls", params={"q": "   "}, headers=auth_headers)

        for r in (empty, spaces):
            assert r.status_code == 200
            assert set(_codes(r)) == {"blank1", "blank2"}
            assert r.json()["total"] == 2

    @pytest.mark.parametrize(
        ("url_type", "expected"),
        [("standard", {"std1"}), ("custom", {"cus1"}), ("campaign", {"cmp1"})],
    )
    def test_url_type_filter(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        url_type: str,
        expected: set[str],
    ):
        campaign = _make_campaign(db_session, test_user)
        _make_url(db_session, test_user, "std1")
        _make_url(db_session, test_user, "cus1", url_type=URLType.CUSTOM)
        _make_url(
            db_session,
            test_user,
            "cmp1",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            user_data={"firstName": "Ada"},
        )

        r = client.get(f"/api/v1/urls?url_type={url_type}", headers=auth_headers)

        assert r.status_code == 200
        assert set(_codes(r)) == expected
        assert r.json()["total"] == 1

    def test_invalid_url_type_is_422(self, client: TestClient, auth_headers: dict):
        r = client.get("/api/v1/urls?url_type=bogus", headers=auth_headers)

        assert r.status_code == 422

    def test_repeated_url_type_matches_any_of_them(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        # The Links view hides per-recipient campaign links by asking for standard + custom.
        campaign = _make_campaign(db_session, test_user)
        _make_url(db_session, test_user, "std1")
        _make_url(db_session, test_user, "cus1", url_type=URLType.CUSTOM)
        _make_url(db_session, test_user, "cmp1", url_type=URLType.CAMPAIGN, campaign_id=campaign.id)

        r = client.get("/api/v1/urls?url_type=standard&url_type=custom", headers=auth_headers)

        assert r.status_code == 200
        assert set(_codes(r)) == {"std1", "cus1"}
        assert r.json()["total"] == 2

    def test_repeated_url_type_combines_with_q(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        campaign = _make_campaign(db_session, test_user)
        _make_url(db_session, test_user, "lstd1", title="Launch A")
        _make_url(db_session, test_user, "ostd1", title="Other")
        _make_url(
            db_session,
            test_user,
            "lcmp1",
            title="Launch C",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
        )

        r = client.get(
            "/api/v1/urls?q=launch&url_type=standard&url_type=custom", headers=auth_headers
        )

        assert r.status_code == 200
        assert _codes(r) == ["lstd1"]
        assert r.json()["total"] == 1

    def test_q_and_url_type_combine_with_and(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "lstd1", title="Launch A")
        _make_url(db_session, test_user, "lcus1", title="Launch B", url_type=URLType.CUSTOM)
        _make_url(db_session, test_user, "ocus1", title="Other", url_type=URLType.CUSTOM)

        r = client.get("/api/v1/urls?q=launch&url_type=custom", headers=auth_headers)

        assert r.status_code == 200
        assert _codes(r) == ["lcus1"]
        assert r.json()["total"] == 1

    def test_q_combines_with_tag_filter(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        tag = Tag(name="promo", display_name="Promo", color="gray-500", created_by=test_user.id)
        db_session.add(tag)
        db_session.commit()
        _make_url(db_session, test_user, "tagged1", title="Launch", tags=[tag])
        _make_url(db_session, test_user, "untag1", title="Launch")
        _make_url(db_session, test_user, "tagged2", title="Other", tags=[tag])

        r = client.get(f"/api/v1/urls?q=launch&tags={tag.id}", headers=auth_headers)

        assert r.status_code == 200
        assert _codes(r) == ["tagged1"]
        assert r.json()["total"] == 1

    def test_total_reflects_filters_across_pages(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        for i in range(3):
            _make_url(db_session, test_user, f"hit{i}", title=f"Launch {i}")
        _make_url(db_session, test_user, "miss1", title="Other")

        first = client.get("/api/v1/urls?q=launch&limit=2", headers=auth_headers)
        second = client.get("/api/v1/urls?q=launch&skip=2&limit=2", headers=auth_headers)

        assert len(first.json()["urls"]) == 2
        assert first.json()["total"] == 3
        assert len(second.json()["urls"]) == 1
        assert second.json()["total"] == 3
        assert set(_codes(first)) | set(_codes(second)) == {"hit0", "hit1", "hit2"}

    def test_q_is_scoped_to_current_user(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        _make_url(db_session, test_user, "mine01", title="Launch")
        _make_url(db_session, _make_other_user(db_session), "theirs", title="Launch")

        r = client.get("/api/v1/urls?q=launch", headers=auth_headers)

        assert _codes(r) == ["mine01"]
        assert r.json()["total"] == 1

    def test_no_filters_keeps_created_at_desc_order(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        now = datetime.utcnow()
        _make_url(db_session, test_user, "oldest", created_at=now - timedelta(days=3))
        _make_url(db_session, test_user, "newest", created_at=now - timedelta(days=1))
        _make_url(db_session, test_user, "middle", created_at=now - timedelta(days=2))

        r = client.get("/api/v1/urls", headers=auth_headers)

        assert r.status_code == 200
        assert _codes(r) == ["newest", "middle", "oldest"]
        assert r.json()["total"] == 3


# ---------------------------------------------------------------------------
# POST /api/v1/urls/fetch-metadata
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFetchMetadata:
    @pytest.fixture
    def fetch_calls(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        calls: list[str] = []

        async def _fake(url, *_args, **_kwargs):
            calls.append(url)
            return OpenGraphMetadata(
                title="Example title",
                description="Example description",
                image_url="https://example.com/og.png",
                url=url,
            )

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _fake)
        return calls

    def test_returns_fetched_metadata(
        self, client: TestClient, auth_headers: dict, fetch_calls: list[str]
    ):
        r = client.post(
            "/api/v1/urls/fetch-metadata",
            json={"url": "https://example.com/article"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json() == {
            "og_title": "Example title",
            "og_description": "Example description",
            "og_image_url": "https://example.com/og.png",
        }
        assert fetch_calls == ["https://example.com/article"]

    def test_missing_metadata_returns_nulls(
        self, client: TestClient, auth_headers: dict, no_og_fetch
    ):
        r = client.post(
            "/api/v1/urls/fetch-metadata",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json() == {"og_title": None, "og_description": None, "og_image_url": None}

    def test_fetch_failure_never_500s(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        async def _boom(*_args, **_kwargs):
            raise RuntimeError("upstream exploded")

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _boom)

        r = client.post(
            "/api/v1/urls/fetch-metadata",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        assert r.status_code == 200
        assert r.json() == {"og_title": None, "og_description": None, "og_image_url": None}

    @pytest.mark.parametrize(
        "bad_url", ["not-a-url", "javascript:alert(1)", "ftp://example.com/file", ""]
    )
    def test_invalid_url_is_422_without_fetching(
        self, client: TestClient, auth_headers: dict, fetch_calls: list[str], bad_url: str
    ):
        r = client.post("/api/v1/urls/fetch-metadata", json={"url": bad_url}, headers=auth_headers)

        assert r.status_code == 422
        assert fetch_calls == []

    def test_requires_auth(self, client: TestClient, fetch_calls: list[str]):
        r = client.post("/api/v1/urls/fetch-metadata", json={"url": "https://example.com"})

        assert r.status_code == 401
        assert fetch_calls == []

    def test_does_not_shadow_custom_create(
        self, client: TestClient, auth_headers: dict, fetch_calls: list[str]
    ):
        r = client.post(
            "/api/v1/urls/custom",
            json={"url": "https://example.com", "custom_code": "still-works"},
            headers=auth_headers,
        )

        assert r.status_code == 201
        assert r.json()["short_code"] == "still-works"
        assert r.json()["url_type"] == "custom"


# ---------------------------------------------------------------------------
# GET /api/v1/analytics/overview — top_urls
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestOverviewTopURLs:
    def test_top_urls_include_short_url_and_title(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        titled = _make_url(db_session, test_user, "top1", title="Top One")
        _add_visits(db_session, titled, humans=2)
        _make_url(db_session, test_user, "top2")

        r = client.get("/api/v1/analytics/overview", headers=auth_headers)

        assert r.status_code == 200
        items = {i["short_code"]: i for i in r.json()["top_urls"]}
        assert items["top1"] == {
            "short_code": "top1",
            "short_url": build_short_url("top1"),
            "title": "Top One",
            "original_url": "https://example.com",
            "url_type": "standard",
            "clicks": 2,
        }
        assert items["top2"]["short_url"] == build_short_url("top2")
        assert items["top2"]["title"] is None
        assert items["top2"]["clicks"] == 0

    @pytest.mark.parametrize("include_bots", ["false", "true"])
    def test_top_urls_clicks_never_count_pixel_opens(
        self,
        client: TestClient,
        auth_headers: dict,
        db_session: Session,
        test_user: User,
        include_bots: str,
    ):
        """Same click definition as `_exclude_bots` (and `click_count`)."""
        opened = _make_url(db_session, test_user, "opened")
        _add_visits(db_session, opened, humans=1, pixels=3)
        clicked = _make_url(db_session, test_user, "clicked")
        _add_visits(db_session, clicked, humans=2)

        r = client.get(
            f"/api/v1/analytics/overview?include_bots={include_bots}", headers=auth_headers
        )

        assert r.status_code == 200
        top = r.json()["top_urls"]
        assert [(i["short_code"], i["clicks"]) for i in top] == [("clicked", 2), ("opened", 1)]

    def test_top_urls_clicks_match_list_click_count(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User
    ):
        url = _make_url(db_session, test_user, "same01")
        _add_visits(db_session, url, humans=2, bots=5, pixels=7)

        overview = client.get("/api/v1/analytics/overview", headers=auth_headers).json()
        listing = client.get("/api/v1/urls", headers=auth_headers).json()

        assert overview["top_urls"][0]["clicks"] == 2
        assert listing["urls"][0]["click_count"] == 2


# ---------------------------------------------------------------------------
# Campaign short URLs — same host resolution as URL responses
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestCampaignShortURLHost:
    CSV = "firstName\nAda\nGrace"

    def _create_campaign(self, client: TestClient, auth_headers: dict) -> str:
        r = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Host check",
                "original_url": "https://example.com/landing",
                "csv_data": self.CSV,
            },
            headers=auth_headers,
        )
        assert r.status_code == 201
        return r.json()["id"]

    def test_campaign_detail_short_urls_share_host_with_url_responses(
        self, client: TestClient, auth_headers: dict, no_og_fetch
    ):
        created = client.post(
            "/api/v1/urls", json={"url": "https://example.com"}, headers=auth_headers
        )
        assert created.status_code == 201
        url_parts = urlsplit(created.json()["short_url"])

        campaign_id = self._create_campaign(client, auth_headers)
        detail = client.get(f"/api/v1/campaigns/{campaign_id}", headers=auth_headers)

        assert detail.status_code == 200
        campaign_urls = detail.json()["urls"]
        assert len(campaign_urls) == 2
        for item in campaign_urls:
            parts = urlsplit(item["short_url"])
            assert (parts.scheme, parts.netloc) == (url_parts.scheme, url_parts.netloc)
            assert item["short_url"] == build_short_url(item["short_code"])

    def test_campaign_detail_and_export_honour_base_url(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(settings, "base_url", "https://go.example.test/")
        campaign_id = self._create_campaign(client, auth_headers)

        detail = client.get(f"/api/v1/campaigns/{campaign_id}", headers=auth_headers)
        export = client.get(f"/api/v1/campaigns/{campaign_id}/export", headers=auth_headers)

        assert detail.status_code == 200
        for item in detail.json()["urls"]:
            assert item["short_url"] == f"https://go.example.test/{item['short_code']}"

        assert export.status_code == 200
        rows = list(csv.DictReader(io.StringIO(export.text)))
        assert len(rows) == 2
        for row in rows:
            assert row["short_url"] == f"https://go.example.test/{row['short_code']}"


# ---------------------------------------------------------------------------
# build_short_url — shared helper (moved to server.utils.url)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildShortURL:
    def test_is_the_same_callable_everywhere(self):
        from server.app.campaigns import build_short_url as campaigns_build
        from server.app.urls import build_short_url as urls_build

        assert urls_build is build_short_url
        assert campaigns_build is build_short_url

    def test_base_url_override_wins(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "base_url", "https://staging.example.test/")

        assert build_short_url("abc123") == "https://staging.example.test/abc123"

    def test_default_domain_used_when_no_base_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "base_url", "")
        monkeypatch.setattr(settings, "default_domain", "s.example.test")

        assert build_short_url("abc123") == "https://s.example.test/abc123"

    def test_localhost_fallback_for_local_dev(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(settings, "base_url", "")
        monkeypatch.setattr(settings, "default_domain", "localhost")
        monkeypatch.setattr(settings, "is_lambda", False)

        assert build_short_url("abc123") == "http://localhost:8000/abc123"


# ---------------------------------------------------------------------------
# Dev CORS default + MCP operationIds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_default_cors_origins_allow_frontend_dev_server(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    origins = Settings(_env_file=None).cors_origins

    assert "http://localhost:4232" in origins
    # Existing dev origins stay allowed (backward compatible).
    assert "http://localhost:4321" in origins
    assert "http://localhost:3000" in origins


@pytest.mark.unit
def test_new_routes_have_the_operation_ids_mapped_for_mcp():
    """`mcp_server.server.MCP_TOOL_NAMES` keys these operationIds to clean names."""
    from main import app

    operation_ids = {
        op["operationId"]
        for path_item in app.openapi()["paths"].values()
        for op in path_item.values()
        if isinstance(op, dict) and "operationId" in op
    }

    assert "get_url_api_v1_urls__short_code__get" in operation_ids
    assert "fetch_url_metadata_api_v1_urls_fetch_metadata_post" in operation_ids
