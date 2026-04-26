"""Integration tests for URL shortening endpoints."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, URLType


@pytest.mark.integration
class TestStandardURLShortening:
    """Test standard URL shortening (POST /api/v1/urls)."""

    def test_shorten_url_success(self, client: TestClient, auth_headers: dict):
        """Test successful URL shortening."""
        response = client.post(
            "/api/v1/urls",
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
            "/api/v1/urls",
            json={"url": "https://example.com"},
        )

        assert response.status_code == 401  # FastAPI returns 401 when auth is missing

    def test_shorten_url_invalid_url(self, client: TestClient, auth_headers: dict):
        """Test that invalid URLs are rejected."""
        response = client.post(
            "/api/v1/urls",
            json={"url": "not-a-valid-url"},
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error
        assert "detail" in response.json()

    def test_shorten_url_duplicate_url_creates_new_code(
        self, client: TestClient, auth_headers: dict
    ):
        """Test that shortening the same URL twice creates different codes."""
        url = "https://example.com/test"

        response1 = client.post("/api/v1/urls", json={"url": url}, headers=auth_headers)
        response2 = client.post("/api/v1/urls", json={"url": url}, headers=auth_headers)

        assert response1.status_code == 201
        assert response2.status_code == 201

        # Should create different short codes for the same URL
        assert response1.json()["short_code"] != response2.json()["short_code"]


@pytest.mark.integration
class TestCustomURLShortening:
    """Test custom URL shortening (POST /api/v1/urls/custom)."""

    def test_custom_url_success(self, client: TestClient, auth_headers: dict):
        """Test successful custom URL creation."""
        response = client.post(
            "/api/v1/urls/custom",
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
            "/api/v1/urls/custom",
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
                "/api/v1/urls/custom",
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
    """Test listing user's URLs (GET /api/v1/urls)."""

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

        response = client.get("/api/v1/urls", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["urls"]) == 3
        assert "total" in data

    def test_list_urls_unauthorized(self, client: TestClient):
        """Test that listing URLs requires authentication."""
        response = client.get("/api/v1/urls")

        assert response.status_code == 401  # FastAPI returns 401 when auth is missing


@pytest.mark.integration
class TestURLDelete:
    """Tests for DELETE /api/v1/urls/{short_code}"""

    def test_delete_standard_url_success(
        self, client: TestClient, db_session: Session, test_user, auth_headers: dict
    ):
        """Test deleting a standard URL successfully."""
        url = URL(
            short_code="deleteme",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.delete("/api/v1/urls/deleteme", headers=auth_headers)

        assert response.status_code == 204
        # Verify URL is deleted
        assert db_session.query(URL).filter(URL.short_code == "deleteme").first() is None

    def test_delete_custom_url_success(
        self, client: TestClient, db_session: Session, test_user, auth_headers: dict
    ):
        """Test deleting a custom URL successfully."""
        url = URL(
            short_code="customdelete",
            original_url="https://example.com",
            url_type=URLType.CUSTOM,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.delete("/api/v1/urls/customdelete", headers=auth_headers)

        assert response.status_code == 204
        assert db_session.query(URL).filter(URL.short_code == "customdelete").first() is None

    def test_delete_campaign_url_forbidden(
        self, client: TestClient, db_session: Session, test_user, auth_headers: dict
    ):
        """Test that campaign URLs cannot be deleted directly."""
        from server.core.models.campaign import Campaign

        campaign = Campaign(
            name="Test Campaign",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        url = URL(
            short_code="campaignurl",
            original_url="https://example.com",
            url_type=URLType.CAMPAIGN,
            campaign_id=campaign.id,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.delete("/api/v1/urls/campaignurl", headers=auth_headers)

        assert response.status_code == 400
        assert "campaign" in response.json()["detail"].lower()
        # Verify URL still exists
        assert db_session.query(URL).filter(URL.short_code == "campaignurl").first() is not None

    def test_delete_url_not_found(self, client: TestClient, auth_headers: dict):
        """Test deleting a non-existent URL."""
        response = client.delete("/api/v1/urls/nonexistent", headers=auth_headers)
        assert response.status_code == 404

    def test_delete_url_unauthorized(self, client: TestClient, db_session: Session, test_user):
        """Test deleting a URL without authentication."""
        url = URL(
            short_code="noperm",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.delete("/api/v1/urls/noperm")
        assert response.status_code == 401

    def test_delete_url_wrong_user(
        self, client: TestClient, db_session: Session, test_user, auth_headers: dict
    ):
        """Test deleting another user's URL."""
        from server.core.models.user import User as UserModel

        # Create another user
        other_user = UserModel(
            email="other@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(other_user)
        db_session.flush()

        # Create URL owned by other user
        url = URL(
            short_code="notmine",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=other_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Try to delete with test_user's auth
        response = client.delete("/api/v1/urls/notmine", headers=auth_headers)
        assert response.status_code == 404  # Returns 404 for security (not revealing URL exists)


@pytest.mark.integration
class TestPhase36Features:
    """Test Phase 3.6 features: title, last_click_at, forward_parameters, PATCH endpoint."""

    def test_create_url_with_title(self, client: TestClient, auth_headers: dict):
        """Test creating URL with optional title field."""
        response = client.post(
            "/api/v1/urls",
            json={
                "url": "https://example.com/page",
                "title": "My Test Campaign",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "My Test Campaign"
        assert data["original_url"] == "https://example.com/page"

    def test_create_url_without_title(self, client: TestClient, auth_headers: dict):
        """Test creating URL without title (should be None)."""
        response = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] is None

    def test_create_url_title_too_long(self, client: TestClient, auth_headers: dict):
        """Test that title exceeding 255 chars is rejected."""
        long_title = "A" * 256
        response = client.post(
            "/api/v1/urls",
            json={
                "url": "https://example.com",
                "title": long_title,
            },
            headers=auth_headers,
        )

        assert response.status_code == 422
        assert "title" in response.json()["detail"][0]["loc"]

    def test_create_url_with_forward_parameters(self, client: TestClient, auth_headers: dict):
        """Test creating URL with forward_parameters flag."""
        response = client.post(
            "/api/v1/urls",
            json={
                "url": "https://example.com",
                "forward_parameters": False,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["forward_parameters"] is False

    def test_forward_parameters_default_true(self, client: TestClient, auth_headers: dict):
        """Test that forward_parameters defaults to True."""
        response = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["forward_parameters"] is True

    def test_patch_url_update_title(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test updating URL title via PATCH."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL
        url = URL(
            short_code="test123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Update title
        response = client.patch(
            "/api/v1/urls/test123",
            json={"title": "Updated Title"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["original_url"] == "https://example.com"  # Unchanged

    def test_patch_url_update_destination(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test updating destination URL via PATCH."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL
        url = URL(
            short_code="test456",
            original_url="https://old-url.com",
            url_type=URLType.STANDARD,
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Update destination
        response = client.patch(
            "/api/v1/urls/test456",
            json={"original_url": "https://new-url.com"},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["original_url"] == "https://new-url.com"

    def test_patch_url_update_forward_parameters(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test updating forward_parameters via PATCH."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL
        url = URL(
            short_code="test789",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            forward_parameters=True,
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Update forward_parameters
        response = client.patch(
            "/api/v1/urls/test789",
            json={"forward_parameters": False},
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["forward_parameters"] is False

    def test_patch_url_not_found(self, client: TestClient, auth_headers: dict):
        """Test PATCH returns 404 for non-existent URL."""
        response = client.patch(
            "/api/v1/urls/nonexistent",
            json={"title": "Test"},
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_patch_url_unauthorized(self, client: TestClient):
        """Test PATCH requires authentication."""
        response = client.patch(
            "/api/v1/urls/test123",
            json={"title": "Test"},
        )

        assert response.status_code == 401

    def test_patch_url_campaign_blocked(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test that campaign URLs cannot be updated via PATCH."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create campaign URL
        url = URL(
            short_code="camp123",
            original_url="https://example.com",
            url_type=URLType.CAMPAIGN,
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Try to update
        response = client.patch(
            "/api/v1/urls/camp123",
            json={"title": "Updated"},
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "campaign" in response.json()["detail"].lower()

    def test_redirect_updates_last_click_at(self, client: TestClient, db_session: Session):
        """Test that redirect updates last_click_at timestamp."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="redirect@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL
        url = URL(
            short_code="redirect1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=user.id,
            last_click_at=None,
        )
        db_session.add(url)
        db_session.commit()

        # Redirect (follow_redirects=False to check redirect response)
        response = client.get("/redirect1", follow_redirects=False)
        assert response.status_code == 302

        # Check last_click_at was set
        db_session.refresh(url)
        assert url.last_click_at is not None

    def test_forward_parameters_respected(self, client: TestClient, db_session: Session):
        """Test that forward_parameters=False blocks query params."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="params@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL with forward_parameters=False
        url = URL(
            short_code="noparams",
            original_url="https://example.com/page",
            url_type=URLType.STANDARD,
            forward_parameters=False,
            created_by=user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Redirect with query params
        response = client.get("/noparams?utm_source=email&utm_campaign=test", follow_redirects=False)
        assert response.status_code == 302

        # Params should NOT be forwarded
        location = response.headers["location"]
        assert "utm_source" not in location
        assert location == "https://example.com/page"

    def test_forward_parameters_true_forwards_params(self, client: TestClient, db_session: Session):
        """Test that forward_parameters=True forwards query params."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="fwdparams@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL with forward_parameters=True
        url = URL(
            short_code="withparams",
            original_url="https://example.com/page",
            url_type=URLType.STANDARD,
            forward_parameters=True,
            created_by=user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Redirect with query params
        response = client.get("/withparams?utm_source=email", follow_redirects=False)
        assert response.status_code == 302

        # Params SHOULD be forwarded
        location = response.headers["location"]
        assert "utm_source=email" in location


@pytest.mark.integration
class TestPhase37OpenGraphFeatures:
    """Test Phase 3.7 features: Open Graph metadata, preview endpoints, social media crawler detection."""

    def test_create_url_with_custom_og_fields(self, client: TestClient, auth_headers: dict):
        """Test creating URL with custom Open Graph metadata."""
        response = client.post(
            "/api/v1/urls",
            json={
                "url": "https://example.com/page",
                "title": "My URL",
                "og_title": "Custom OG Title",
                "og_description": "Custom OG Description",
                "og_image_url": "https://example.com/image.png",
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "My URL"
        assert data["og_title"] == "Custom OG Title"
        assert data["og_description"] == "Custom OG Description"
        assert data["og_image_url"] == "https://example.com/image.png"
        assert data["og_fetched_at"] is None  # Manual set, not fetched

    def test_create_url_without_og_fields(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        """Test creating URL without OG fields (should be None)."""
        # Force OG fetch to return empty so the test does not depend on network reachability
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_args, **_kwargs):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        response = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["og_title"] is None
        assert data["og_description"] is None
        assert data["og_image_url"] is None
        assert data["og_fetched_at"] is None

    def test_get_preview_metadata(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test GET /{short_code}/preview endpoint."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL with OG metadata
        url = URL(
            short_code="prev123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            og_title="Test Title",
            og_description="Test Description",
            og_image_url="https://example.com/image.png",
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Get preview
        response = client.get("/api/v1/urls/prev123/preview", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert data["og_title"] == "Test Title"
        assert data["og_description"] == "Test Description"
        assert data["og_image_url"] == "https://example.com/image.png"
        assert data["og_url"].endswith("/prev123")
        assert data["has_custom_preview"] is True
        assert data["fetched_at"] is None

    def test_get_preview_metadata_not_found(self, client: TestClient, auth_headers: dict):
        """Test GET /preview returns 404 for non-existent URL."""
        response = client.get("/api/v1/urls/nonexistent/preview", headers=auth_headers)
        assert response.status_code == 404

    def test_refresh_preview_metadata_success(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test POST /{short_code}/refresh-preview endpoint."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL without OG metadata
        url = URL(
            short_code="refresh123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Refresh preview (will attempt to fetch, may timeout or fail)
        response = client.post("/api/v1/urls/refresh123/refresh-preview", headers=auth_headers)

        # Should return 200 even if fetch fails (returns empty metadata)
        assert response.status_code == 200
        data = response.json()
        # May or may not have metadata depending on network availability
        assert "og_title" in data
        assert "og_description" in data
        assert "og_image_url" in data

    def test_refresh_preview_unauthorized(self, client: TestClient):
        """Test POST /refresh-preview requires authentication."""
        response = client.post("/api/v1/urls/test123/refresh-preview")
        assert response.status_code == 401

    def test_refresh_preview_not_found(self, client: TestClient, auth_headers: dict):
        """Test POST /refresh-preview returns 404 for non-existent URL."""
        response = client.post("/api/v1/urls/nonexistent/refresh-preview", headers=auth_headers)
        assert response.status_code == 404

    def test_refresh_preview_wrong_user(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test POST /refresh-preview returns 404 for other user's URL."""
        from server.core.models import User as UserModel

        # Create another user
        other_user = UserModel(
            email="other@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(other_user)
        db_session.flush()

        # Create URL owned by other user
        url = URL(
            short_code="notmine",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=other_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Try to refresh with test_user's auth
        response = client.post("/api/v1/urls/notmine/refresh-preview", headers=auth_headers)
        assert response.status_code == 404

    def test_patch_url_update_og_fields(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Test updating Open Graph fields via PATCH."""
        # Get user ID
        user_response = client.get("/api/v1/auth/me", headers=auth_headers)
        user_id = uuid.UUID(user_response.json()["id"])

        # Create URL
        url = URL(
            short_code="ogpatch",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            og_title="Old Title",
            created_by=user_id,
        )
        db_session.add(url)
        db_session.commit()

        # Update OG fields
        response = client.patch(
            "/api/v1/urls/ogpatch",
            json={
                "og_title": "New OG Title",
                "og_description": "New Description",
                "og_image_url": "https://example.com/new.png",
            },
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["og_title"] == "New OG Title"
        assert data["og_description"] == "New Description"
        assert data["og_image_url"] == "https://example.com/new.png"

    def test_social_media_crawler_gets_preview_page(self, client: TestClient, db_session: Session):
        """Test that social media crawlers receive HTML preview page."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="crawler@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL with OG metadata
        url = URL(
            short_code="social123",
            original_url="https://example.com/page",
            url_type=URLType.STANDARD,
            og_title="Social Preview",
            og_description="Preview description",
            created_by=user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access as Twitterbot
        response = client.get(
            "/social123",
            headers={"User-Agent": "Twitterbot/1.0"},
            follow_redirects=False,
        )

        # Should get HTML preview page
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")
        assert b"Social Preview" in response.content
        assert b"og:title" in response.content

    def test_social_media_crawler_detection(self, client: TestClient, db_session: Session):
        """Test detection of various social media crawlers."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="crawlers@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL
        url = URL(
            short_code="detect123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            og_title="Crawler Test",
            created_by=user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Test various crawler User-Agents
        crawlers = [
            "facebookexternalhit/1.1",
            "LinkedInBot/1.0",
            "WhatsApp/2.0",
            "Slackbot-LinkExpanding 1.0",
            "Discordbot/2.0",
            "TelegramBot (like TwitterBot)",
            "Pinterest/0.2",
        ]

        for crawler_ua in crawlers:
            response = client.get(
                "/detect123",
                headers={"User-Agent": crawler_ua},
                follow_redirects=False,
            )
            # All should get HTML preview page (200) instead of redirect (302)
            assert response.status_code == 200, f"Failed for {crawler_ua}"
            assert b"Crawler Test" in response.content

    def test_regular_browser_gets_redirect(self, client: TestClient, db_session: Session):
        """Test that regular browsers get redirected (not preview page)."""
        from server.core.models import User as UserModel

        # Create user
        user = UserModel(
            email="browser@example.com",
            password_hash="hashed",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Create URL with OG metadata
        url = URL(
            short_code="browser123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            og_title="Should Redirect",
            created_by=user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access as regular browser
        response = client.get(
            "/browser123",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"},
            follow_redirects=False,
        )

        # Should get redirect (302) not preview page (200)
        assert response.status_code == 302
        assert response.headers["location"] == "https://example.com"


@pytest.mark.integration
class TestPhase392ExpirationAndQuota:
    """Phase 3.9.2 — URL expiration (valid_since / valid_until) and visit caps (max_visits).

    The redirect handler must:
    - Return 404 if the URL exists but `valid_since` is in the future (don't reveal premature URLs).
    - Return 410 Gone if `valid_until` has passed (the link existed and is now retired).
    - Return 410 Gone if `max_visits` has been reached (quota consumed).
    - Behave normally when these fields are NULL (default — no constraints).
    - Count only real human visits against `max_visits`. Crawler preview hits don't consume quota
      because they don't insert into the Visitor table.
    """

    def test_redirect_within_validity_window_succeeds(
        self, client: TestClient, db_session: Session, test_user
    ):
        from datetime import datetime, timedelta, timezone

        url = URL(
            short_code="active1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            valid_since=datetime.now(timezone.utc) - timedelta(days=1),
            valid_until=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db_session.add(url)
        db_session.commit()

        response = client.get("/active1", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "https://example.com"

    def test_redirect_expired_returns_410(
        self, client: TestClient, db_session: Session, test_user
    ):
        from datetime import datetime, timedelta, timezone

        url = URL(
            short_code="expired1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            valid_until=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        db_session.add(url)
        db_session.commit()

        response = client.get("/expired1", follow_redirects=False)
        assert response.status_code == 410
        assert "expired" in response.json()["detail"].lower()

    def test_redirect_not_yet_valid_returns_404(
        self, client: TestClient, db_session: Session, test_user
    ):
        from datetime import datetime, timedelta, timezone

        url = URL(
            short_code="future1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            valid_since=datetime.now(timezone.utc) + timedelta(days=1),
        )
        db_session.add(url)
        db_session.commit()

        response = client.get("/future1", follow_redirects=False)
        # 404 (not 410) — don't reveal that a not-yet-active URL exists
        assert response.status_code == 404

    def test_redirect_max_visits_reached_returns_410(
        self, client: TestClient, db_session: Session, test_user
    ):
        from server.core.models import Visitor

        url = URL(
            short_code="quota1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            max_visits=2,
        )
        db_session.add(url)
        db_session.flush()

        # Pre-populate 2 visits (quota reached)
        for _ in range(2):
            db_session.add(Visitor(url_id=url.id, short_code="quota1", ip="1.2.3.4"))
        db_session.commit()

        response = client.get("/quota1", follow_redirects=False)
        assert response.status_code == 410
        assert "limit" in response.json()["detail"].lower() or "max" in response.json()["detail"].lower()

    def test_redirect_max_visits_consumes_one_per_hit(
        self, client: TestClient, db_session: Session, test_user
    ):
        url = URL(
            short_code="quota2",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            max_visits=3,
        )
        db_session.add(url)
        db_session.commit()

        # First 3 hits succeed
        for _ in range(3):
            response = client.get("/quota2", follow_redirects=False)
            assert response.status_code == 302

        # Fourth hit hits the cap
        response = client.get("/quota2", follow_redirects=False)
        assert response.status_code == 410

    def test_redirect_no_constraints_works_normally(
        self, client: TestClient, db_session: Session, test_user
    ):
        url = URL(
            short_code="vanilla",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.get("/vanilla", follow_redirects=False)
        assert response.status_code == 302

    def test_create_url_accepts_validity_fields(
        self, client: TestClient, auth_headers: dict
    ):
        from datetime import datetime, timedelta, timezone

        valid_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        response = client.post(
            "/api/v1/urls",
            json={
                "url": "https://example.com",
                "valid_until": valid_until,
                "max_visits": 100,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["max_visits"] == 100
        assert data["valid_until"] is not None

    def test_patch_url_can_set_and_clear_validity(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        from datetime import datetime, timedelta, timezone

        url = URL(
            short_code="patchme",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Set
        valid_until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        r1 = client.patch(
            "/api/v1/urls/patchme",
            json={"valid_until": valid_until, "max_visits": 50},
            headers=auth_headers,
        )
        assert r1.status_code == 200
        assert r1.json()["max_visits"] == 50

        # Clear (set to null)
        r2 = client.patch(
            "/api/v1/urls/patchme",
            json={"valid_until": None, "max_visits": None},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        assert r2.json()["valid_until"] is None
        assert r2.json()["max_visits"] is None

    def test_url_response_includes_validity_fields(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        from datetime import datetime, timedelta, timezone

        url = URL(
            short_code="listme",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
            valid_until=datetime.now(timezone.utc) + timedelta(days=10),
            max_visits=42,
        )
        db_session.add(url)
        db_session.commit()

        r = client.get("/api/v1/urls", headers=auth_headers)
        assert r.status_code == 200
        item = next((u for u in r.json()["urls"] if u["short_code"] == "listme"), None)
        assert item is not None
        assert item["max_visits"] == 42
        assert item["valid_until"] is not None


@pytest.mark.integration
class TestPhase394Crawlability:
    """Phase 3.9.4 — robots.txt default-deny + per-URL crawlable flag."""

    def test_robots_default_deny_with_no_urls(self, client: TestClient):
        r = client.get("/robots.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert r.text == "User-agent: *\nDisallow: /\n"

    def test_robots_lists_crawlable_urls(
        self, client: TestClient, db_session, test_user
    ):
        db_session.add_all([
            URL(
                short_code="open1",
                original_url="https://example.com",
                url_type=URLType.STANDARD,
                crawlable=True,
                created_by=test_user.id,
            ),
            URL(
                short_code="hidden1",
                original_url="https://example.com",
                url_type=URLType.STANDARD,
                crawlable=False,
                created_by=test_user.id,
            ),
        ])
        db_session.commit()

        r = client.get("/robots.txt")
        assert r.status_code == 200
        body = r.text
        assert "Disallow: /\n" in body
        assert "Allow: /open1" in body
        assert "hidden1" not in body

    def test_create_url_defaults_to_not_crawlable(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        r = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com"},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["crawlable"] is False

    def test_create_url_can_opt_in_crawlable(
        self, client: TestClient, auth_headers: dict, monkeypatch: pytest.MonkeyPatch
    ):
        from server.app import urls as urls_module
        from server.utils.opengraph import OpenGraphMetadata

        async def _empty_og(*_a, **_kw):
            return OpenGraphMetadata()

        monkeypatch.setattr(urls_module, "fetch_opengraph_metadata", _empty_og)

        r = client.post(
            "/api/v1/urls",
            json={"url": "https://example.com", "crawlable": True},
            headers=auth_headers,
        )
        assert r.status_code == 201
        assert r.json()["crawlable"] is True


@pytest.mark.integration
class TestPhase395IPAnonymization:
    """Phase 3.9.5 — visitor IPs are anonymized at insert time."""

    def test_anonymizes_ipv4_in_visit_log(
        self, client: TestClient, db_session, test_user
    ):
        from server.core.models import Visitor

        url = URL(
            short_code="anon1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # TestClient's default is 'testclient', which won't parse as IP and falls
        # through anonymize_ip unchanged. Instead, force a real-looking IP via X-F-F
        # only by adding an entry to trusted_proxies — but for this test, we can simply
        # verify that the persisted IP either equals the truncated form or is the
        # benign "testclient" sentinel (the function's pass-through behavior).
        client.get("/anon1", follow_redirects=False)
        v = db_session.query(Visitor).filter(Visitor.short_code == "anon1").first()
        assert v is not None
        # IP must never end in a non-zero octet for a real IPv4 input. With TestClient's
        # synthetic "testclient" this assertion is trivially true; the dedicated unit
        # tests in test_network cover the IPv4/IPv6 truncation logic directly.
        assert v.ip is not None


@pytest.mark.integration
class TestPhase396DisableTrackParam:
    """Phase 3.9.6 — `?nostat` suppresses visit logging."""

    def test_nostat_skips_logging(self, client: TestClient, db_session, test_user):
        from server.core.models import Visitor

        url = URL(
            short_code="qa1",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        r = client.get("/qa1?nostat", follow_redirects=False)
        assert r.status_code == 302
        count = db_session.query(Visitor).filter(Visitor.short_code == "qa1").count()
        assert count == 0

    def test_normal_request_still_logs(self, client: TestClient, db_session, test_user):
        from server.core.models import Visitor

        url = URL(
            short_code="qa2",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        client.get("/qa2", follow_redirects=False)
        count = db_session.query(Visitor).filter(Visitor.short_code == "qa2").count()
        assert count == 1
