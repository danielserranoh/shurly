"""Phase 3.10.6 — configurable redirect status and Cache-Control."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.config import settings
from server.core.models import URL, User
from server.core.models.url import URLType
from server.utils.domain import get_or_create_default_domain


@pytest.fixture
def short_url(db_session: Session, test_user: User) -> URL:
    domain = get_or_create_default_domain(db_session)
    url = URL(
        short_code="cfg1",
        domain_id=domain.id,
        original_url="https://example.com",
        url_type=URLType.STANDARD,
        created_by=test_user.id,
    )
    db_session.add(url)
    db_session.commit()
    db_session.refresh(url)
    return url


@pytest.mark.integration
class TestConfigurableRedirect:
    def test_default_is_302_with_no_store_cache(
        self, client: TestClient, short_url: URL
    ):
        r = client.get("/cfg1", follow_redirects=False)
        assert r.status_code == 302
        assert "max-age=0" in r.headers.get("cache-control", "")

    @pytest.mark.parametrize("code", [301, 307, 308])
    def test_status_code_override(
        self, client: TestClient, short_url: URL, monkeypatch, code
    ):
        monkeypatch.setattr(settings, "redirect_status_code", code)
        r = client.get("/cfg1", follow_redirects=False)
        assert r.status_code == code
        assert r.headers["location"] == "https://example.com"

    def test_cache_lifetime_emits_public_max_age(
        self, client: TestClient, short_url: URL, monkeypatch
    ):
        monkeypatch.setattr(settings, "redirect_cache_lifetime", 600)
        r = client.get("/cfg1", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["cache-control"] == "public, max-age=600"

    def test_invalid_status_rejected(self, monkeypatch):
        from pydantic import ValidationError

        # Trying to instantiate a Settings with an invalid value must fail validation
        from server.core.config import Settings

        with pytest.raises(ValidationError):
            Settings(redirect_status_code=303)
