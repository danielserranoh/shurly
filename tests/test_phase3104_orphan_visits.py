"""Phase 3.10.4 — orphan visit tracking."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import OrphanVisit, OrphanVisitType, User
from server.utils.domain import get_or_create_default_domain


@pytest.mark.integration
class TestOrphanLogging:
    def test_unknown_short_code_logs_invalid_short_url(
        self, client: TestClient, db_session: Session
    ):
        # Make sure default domain exists so the resolver can run
        get_or_create_default_domain(db_session)

        r = client.get("/typo123", follow_redirects=False)
        assert r.status_code == 404

        rows = db_session.query(OrphanVisit).all()
        assert len(rows) == 1
        assert rows[0].type == OrphanVisitType.INVALID_SHORT_URL
        assert rows[0].attempted_path == "/typo123"

    def test_base_url_hit_logs_base_url_type(
        self, client: TestClient, db_session: Session
    ):
        get_or_create_default_domain(db_session)

        r = client.get("/", follow_redirects=False)
        assert r.status_code == 404

        rows = (
            db_session.query(OrphanVisit)
            .filter(OrphanVisit.type == OrphanVisitType.BASE_URL)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].attempted_path == "/"

    def test_robots_txt_does_not_log_orphan(
        self, client: TestClient, db_session: Session
    ):
        # /robots.txt is a real route — must not be classified as an orphan
        r = client.get("/robots.txt")
        assert r.status_code == 200
        assert db_session.query(OrphanVisit).count() == 0


@pytest.mark.integration
class TestOrphanVisitsEndpoint:
    def test_endpoint_requires_auth(self, client: TestClient):
        r = client.get("/api/v1/analytics/orphan-visits")
        assert r.status_code == 401

    def test_lists_recent_orphans_newest_first(
        self,
        client: TestClient,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        from datetime import datetime, timedelta

        for i, t in enumerate(
            [
                OrphanVisitType.BASE_URL,
                OrphanVisitType.INVALID_SHORT_URL,
                OrphanVisitType.REGULAR_404,
            ]
        ):
            db_session.add(
                OrphanVisit(
                    type=t,
                    attempted_path=f"/p{i}",
                    user_agent="Mozilla/5.0",
                    created_at=datetime.utcnow() - timedelta(minutes=i),
                )
            )
        db_session.commit()

        r = client.get("/api/v1/analytics/orphan-visits", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        # Newest first → /p0 (offset 0 minutes ago)
        assert body["items"][0]["attempted_path"] == "/p0"
