"""Integration tests for URL shortening endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, URLType


@pytest.mark.integration
class TestStandardURLShortening:
    """Test standard URL shortening (POST /api/urls)."""

    def test_shorten_url_success(self, client: TestClient, auth_headers: dict):
        """Test successful URL shortening."""
        response = client.post(
            "/api/urls",
            json={"url": "https://example.com/very/long/path"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert "short_code" in data
        assert "short_url" in data
        assert "original_url" in data
        assert data["original_url"] == "https://example.com/very/long/path"
        assert len(data["short_code"]) == 6

    def test_shorten_url_unauthorized(self, client: TestClient):
        """Test that shortening requires authentication."""
        response = client.post(
            "/api/urls",
            json={"url": "https://example.com"},
        )

        assert response.status_code == 401

    def test_shorten_url_invalid_url(self, client: TestClient, auth_headers: dict):
        """Test that invalid URLs are rejected."""
        response = client.post(
            "/api/urls",
            json={"url": "not-a-valid-url"},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_shorten_url_duplicate_url_creates_new_code(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that shortening the same URL twice creates different codes."""
        url = "https://example.com/test"

        response1 = client.post("/api/urls", json={"url": url}, headers=auth_headers)
        response2 = client.post("/api/urls", json={"url": url}, headers=auth_headers)

        assert response1.status_code == 201
        assert response2.status_code == 201

        # Should create different short codes for the same URL
        assert response1.json()["short_code"] != response2.json()["short_code"]


@pytest.mark.integration
class TestCustomURLShortening:
    """Test custom URL shortening (POST /api/urls/custom)."""

    def test_custom_url_success(self, client: TestClient, auth_headers: dict):
        """Test successful custom URL creation."""
        response = client.post(
            "/api/urls/custom",
            json={"url": "https://example.com", "custom_code": "my-link"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["short_code"] == "my-link"
        assert data["url_type"] == "custom"

    def test_custom_url_code_taken_appends_random(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test that taken custom codes get random characters appended."""
        # Create a URL with the desired code
        existing_url = URL(
            short_code="taken",
            original_url="https://first.com",
            url_type=URLType.CUSTOM,
            created_by=test_user.id,
        )
        db_session.add(existing_url)
        db_session.commit()

        # Try to create another with the same code
        response = client.post(
            "/api/urls/custom",
            json={"url": "https://second.com", "custom_code": "taken"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        # Should have appended random characters
        assert data["short_code"].startswith("taken")
        assert len(data["short_code"]) > len("taken")
        assert "warning" in data  # Should warn user about modification

    def test_custom_url_invalid_code(self, client: TestClient, auth_headers: dict):
        """Test that invalid custom codes are rejected."""
        invalid_codes = ["ab", "test!code", "a" * 25]

        for code in invalid_codes:
            response = client.post(
                "/api/urls/custom",
                json={"url": "https://example.com", "custom_code": code},
                headers=auth_headers,
            )

            assert response.status_code == 400


@pytest.mark.integration
class TestURLRedirect:
    """Test URL redirect endpoint (GET /{short_code})."""

    def test_redirect_success(self, client: TestClient, db_session: Session, test_user):
        """Test successful redirect."""
        # Create a URL
        url = URL(
            short_code="abc123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access the short URL
        response = client.get("/abc123", follow_redirects=False)

        assert response.status_code == 302  # Temporary redirect
        assert response.headers["location"] == "https://example.com"

    def test_redirect_campaign_url_with_params(
        self, client: TestClient, db_session: Session, test_user
    ):
        """Test redirect for campaign URL with user data parameters."""
        # Create a campaign URL with user data
        url = URL(
            short_code="camp123",
            original_url="https://example.com/landing",
            url_type=URLType.CAMPAIGN,
            user_data={"firstName": "John", "lastName": "Doe", "company": "Acme"},
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access the short URL
        response = client.get("/camp123", follow_redirects=False)

        assert response.status_code == 302
        redirect_url = response.headers["location"]

        # Should have query parameters from user_data
        assert "firstName=John" in redirect_url
        assert "lastName=Doe" in redirect_url
        assert "company=Acme" in redirect_url
        assert redirect_url.startswith("https://example.com/landing?")

    def test_redirect_not_found(self, client: TestClient):
        """Test that non-existent codes return 404."""
        response = client.get("/nonexistent")

        assert response.status_code == 404

    def test_redirect_logs_visit(self, client: TestClient, db_session: Session, test_user):
        """Test that redirects log visitor information."""
        # Create a URL
        url = URL(
            short_code="track123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access the short URL
        client.get("/track123", headers={"User-Agent": "TestBot/1.0"})

        # Refresh to get visits
        db_session.refresh(url)

        # Should have logged a visit
        assert len(url.visits) == 1
        visit = url.visits[0]
        assert visit.short_code == "track123"
        assert visit.ip is not None


@pytest.mark.integration
class TestURLList:
    """Test listing user's URLs (GET /api/urls)."""

    def test_list_urls_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test listing user's URLs."""
        # Create some URLs
        for i in range(3):
            url = URL(
                short_code=f"test{i}",
                original_url=f"https://example.com/{i}",
                url_type=URLType.STANDARD,
                created_by=test_user.id,
            )
            db_session.add(url)
        db_session.commit()

        response = client.get("/api/urls", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["urls"]) == 3
        assert "total" in data

    def test_list_urls_unauthorized(self, client: TestClient):
        """Test that listing URLs requires authentication."""
        response = client.get("/api/urls")

        assert response.status_code == 401
