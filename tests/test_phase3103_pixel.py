"""Phase 3.10.3 — email tracking pixel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, User, Visitor
from server.core.models.url import URLType
from server.utils.domain import get_or_create_default_domain


@pytest.mark.integration
class TestTrackingPixel:
    def _make_url(self, db_session: Session, test_user: User, code: str = "px1") -> URL:
        domain = get_or_create_default_domain(db_session)
        url = URL(
            short_code=code,
            domain_id=domain.id,
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()
        db_session.refresh(url)
        return url

    def test_pixel_returns_43_byte_gif(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        self._make_url(db_session, test_user)
        r = client.get("/px1/track")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/gif"
        # Canonical 1×1 GIF89a is 43 bytes
        assert len(r.content) == 43
        assert r.content.startswith(b"GIF89a")

    def test_pixel_sets_no_store_cache(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        self._make_url(db_session, test_user, "px2")
        r = client.get("/px2/track")
        cache = r.headers.get("cache-control", "")
        assert "no-store" in cache

    def test_pixel_logs_visit_with_is_pixel(
        self, client: TestClient, db_session: Session, test_user: User
    ):
        url = self._make_url(db_session, test_user, "px3")
        client.get("/px3/track", headers={"User-Agent": "Mozilla/5.0"})
        v = db_session.query(Visitor).filter(Visitor.url_id == url.id).first()
        assert v is not None
        assert v.is_pixel is True

    def test_pixel_404_for_unknown_code(self, client: TestClient):
        r = client.get("/never/track")
        assert r.status_code == 404

    def test_pixel_does_not_count_as_click_in_overview(
        self, client: TestClient, db_session: Session, test_user: User, auth_headers
    ):
        url = self._make_url(db_session, test_user, "px4")
        # 1 real click + 1 pixel hit
        db_session.add(
            Visitor(
                url_id=url.id,
                short_code="px4",
                ip="1.1.1.1",
                user_agent="Mozilla/5.0",
                is_bot=False,
                is_pixel=False,
            )
        )
        db_session.add(
            Visitor(
                url_id=url.id,
                short_code="px4",
                ip="1.1.1.2",
                user_agent="Mozilla/5.0",
                is_bot=False,
                is_pixel=True,
            )
        )
        db_session.commit()

        r = client.get("/api/v1/analytics/overview", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        # Pixel hit must NOT be counted as a click
        assert body["total_clicks"] == 1
