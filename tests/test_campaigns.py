"""Integration tests for campaign endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import URL, Campaign


@pytest.mark.integration
class TestCreateCampaign:
    """Test campaign creation (POST /api/v1/campaigns)."""

    def test_create_campaign_success(self, client: TestClient, auth_headers: dict):
        """Test successful campaign creation with CSV."""
        csv_data = """firstName,lastName,company
John,Doe,Acme
Jane,Smith,TechCorp"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Q4 Marketing Campaign",
                "original_url": "https://example.com/landing",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert "id" in data
        assert data["name"] == "Q4 Marketing Campaign"
        assert data["original_url"] == "https://example.com/landing"
        assert data["csv_columns"] == ["firstName", "lastName", "company"]
        assert data["url_count"] == 2
        assert "created_at" in data

    def test_create_campaign_creates_urls(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        """Test that campaign creation actually creates URL records."""
        from uuid import UUID

        csv_data = """email,region
test1@example.com,EMEA
test2@example.com,APAC"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test Campaign",
                "original_url": "https://example.com",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        campaign_id = UUID(response.json()["id"])  # Convert string to UUID

        # Check URLs were created in database
        urls = db_session.query(URL).filter(URL.campaign_id == campaign_id).all()
        assert len(urls) == 2

        # Check URL attributes
        assert urls[0].url_type.value == "campaign"
        assert urls[0].user_data is not None
        assert "email" in urls[0].user_data
        assert "region" in urls[0].user_data

    def test_create_campaign_unauthorized(self, client: TestClient):
        """Test that campaign creation requires authentication."""
        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test",
                "original_url": "https://example.com",
                "csv_data": "col1\nval1",
            },
        )

        assert response.status_code == 403

    def test_create_campaign_invalid_url(self, client: TestClient, auth_headers: dict):
        """Test that invalid original URLs are rejected."""
        csv_data = """email\ntest@example.com"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test",
                "original_url": "not-a-valid-url",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_create_campaign_empty_csv(self, client: TestClient, auth_headers: dict):
        """Test that empty CSV data is rejected."""
        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test",
                "original_url": "https://example.com",
                "csv_data": "",
            },
            headers=auth_headers,
        )

        assert response.status_code == 422  # Pydantic validation error

    def test_create_campaign_csv_no_data_rows(self, client: TestClient, auth_headers: dict):
        """Test that CSV with only header is rejected."""
        csv_data = "firstName,lastName,company"

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test",
                "original_url": "https://example.com",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 400
        assert "must have at least one data row" in response.json()["detail"]

    def test_create_campaign_csv_with_extra_values(self, client: TestClient, auth_headers: dict):
        """Test that CSV with extra values in rows is rejected."""
        # When a row has more values than headers, csv.DictReader creates a None key
        # which our validator catches as empty column name
        csv_data = """firstName,lastName
John,Doe,ExtraValue
Jane,Smith"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Test",
                "original_url": "https://example.com",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 400
        # csv.DictReader creates empty column names for extra values
        assert "empty column names" in response.json()["detail"]

    def test_create_campaign_single_row(self, client: TestClient, auth_headers: dict):
        """Test campaign creation with single CSV row."""
        csv_data = """email\ntest@example.com"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Single Row",
                "original_url": "https://example.com",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        assert response.json()["url_count"] == 1

    def test_create_campaign_many_columns(self, client: TestClient, auth_headers: dict):
        """Test campaign with many CSV columns."""
        csv_data = """col1,col2,col3,col4,col5
val1,val2,val3,val4,val5
val6,val7,val8,val9,val10"""

        response = client.post(
            "/api/v1/campaigns",
            json={
                "name": "Many Columns",
                "original_url": "https://example.com",
                "csv_data": csv_data,
            },
            headers=auth_headers,
        )

        assert response.status_code == 201
        assert len(response.json()["csv_columns"]) == 5
        assert response.json()["url_count"] == 2


@pytest.mark.integration
class TestListCampaigns:
    """Test listing campaigns (GET /api/v1/campaigns)."""

    def test_list_campaigns_empty(self, client: TestClient, auth_headers: dict):
        """Test listing campaigns when user has none."""
        response = client.get("/api/v1/campaigns", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["campaigns"] == []
        assert data["total"] == 0

    def test_list_campaigns_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test listing user's campaigns."""
        # Create some campaigns
        for i in range(3):
            campaign = Campaign(
                name=f"Campaign {i}",
                original_url="https://example.com",
                csv_columns=["col1", "col2"],
                created_by=test_user.id,
            )
            db_session.add(campaign)
        db_session.commit()

        response = client.get("/api/v1/campaigns", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert len(data["campaigns"]) == 3
        assert data["total"] == 3

    def test_list_campaigns_pagination(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test campaign listing pagination."""
        # Create 5 campaigns
        for i in range(5):
            campaign = Campaign(
                name=f"Campaign {i}",
                original_url="https://example.com",
                csv_columns=["col1"],
                created_by=test_user.id,
            )
            db_session.add(campaign)
        db_session.commit()

        # Get first page
        response = client.get("/api/v1/campaigns?skip=0&limit=2", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()["campaigns"]) == 2
        assert response.json()["total"] == 5

        # Get second page
        response = client.get("/api/v1/campaigns?skip=2&limit=2", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()["campaigns"]) == 2

    def test_list_campaigns_unauthorized(self, client: TestClient):
        """Test that listing requires authentication."""
        response = client.get("/api/v1/campaigns")

        assert response.status_code == 403


@pytest.mark.integration
class TestGetCampaign:
    """Test getting campaign details (GET /api/v1/campaigns/{id})."""

    def test_get_campaign_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test getting campaign details with URLs."""
        # Create campaign
        campaign = Campaign(
            name="Test Campaign",
            original_url="https://example.com/landing",
            csv_columns=["firstName", "lastName"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        # Create URLs for campaign
        for i, (first, last) in enumerate([("John", "Doe"), ("Jane", "Smith")]):
            url = URL(
                short_code=f"test{i}",
                original_url="https://example.com/landing",
                url_type="campaign",
                campaign_id=campaign.id,
                user_data={"firstName": first, "lastName": last},
                created_by=test_user.id,
            )
            db_session.add(url)
        db_session.commit()

        response = client.get(f"/api/v1/campaigns/{campaign.id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == str(campaign.id)
        assert data["name"] == "Test Campaign"
        assert data["url_count"] == 2
        assert len(data["urls"]) == 2

        # Check URL details
        assert "short_code" in data["urls"][0]
        assert "short_url" in data["urls"][0]
        assert "user_data" in data["urls"][0]
        assert data["urls"][0]["user_data"]["firstName"] in ["John", "Jane"]

    def test_get_campaign_not_found(self, client: TestClient, auth_headers: dict):
        """Test getting non-existent campaign."""
        import uuid

        fake_id = uuid.uuid4()
        response = client.get(f"/api/v1/campaigns/{fake_id}", headers=auth_headers)

        assert response.status_code == 404

    def test_get_campaign_unauthorized(self, client: TestClient):
        """Test that getting campaign requires authentication."""
        import uuid

        response = client.get(f"/api/v1/campaigns/{uuid.uuid4()}")

        assert response.status_code == 403

    def test_get_campaign_wrong_user(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        """Test that users can't access other users' campaigns."""
        # Create different user
        from server.core.models import User

        other_user = User(
            email="other@example.com",
            password_hash="hash",
            is_active=True,
        )
        db_session.add(other_user)
        db_session.flush()

        # Create campaign for other user
        campaign = Campaign(
            name="Other's Campaign",
            original_url="https://example.com",
            csv_columns=["col1"],
            created_by=other_user.id,
        )
        db_session.add(campaign)
        db_session.commit()

        # Try to access with test_user's auth
        response = client.get(f"/api/v1/campaigns/{campaign.id}", headers=auth_headers)

        assert response.status_code == 403


@pytest.mark.integration
class TestExportCampaign:
    """Test exporting campaign URLs as CSV (GET /api/v1/campaigns/{id}/export)."""

    def test_export_campaign_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test exporting campaign URLs as CSV."""
        # Create campaign
        campaign = Campaign(
            name="Export Test",
            original_url="https://example.com/landing",
            csv_columns=["firstName", "lastName", "company"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        # Create URLs
        url1 = URL(
            short_code="exp001",
            original_url="https://example.com/landing",
            url_type="campaign",
            campaign_id=campaign.id,
            user_data={"firstName": "John", "lastName": "Doe", "company": "Acme"},
            created_by=test_user.id,
        )
        url2 = URL(
            short_code="exp002",
            original_url="https://example.com/landing",
            url_type="campaign",
            campaign_id=campaign.id,
            user_data={"firstName": "Jane", "lastName": "Smith", "company": "TechCorp"},
            created_by=test_user.id,
        )
        db_session.add_all([url1, url2])
        db_session.commit()

        response = client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]

        # Parse CSV content
        csv_content = response.text
        lines = csv_content.strip().split("\n")

        # Check header
        assert "short_code" in lines[0]
        assert "short_url" in lines[0]
        assert "firstName" in lines[0]
        assert "lastName" in lines[0]
        assert "company" in lines[0]

        # Check data rows
        assert len(lines) == 3  # Header + 2 data rows
        assert "exp001" in csv_content
        assert "exp002" in csv_content
        assert "John" in csv_content
        assert "Jane" in csv_content

    def test_export_campaign_not_found(self, client: TestClient, auth_headers: dict):
        """Test exporting non-existent campaign."""
        import uuid

        response = client.get(f"/api/v1/campaigns/{uuid.uuid4()}/export", headers=auth_headers)

        assert response.status_code == 404

    def test_export_campaign_no_urls(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test exporting campaign with no URLs."""
        campaign = Campaign(
            name="Empty Campaign",
            original_url="https://example.com",
            csv_columns=["col1"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.commit()

        response = client.get(f"/api/v1/campaigns/{campaign.id}/export", headers=auth_headers)

        assert response.status_code == 404
        assert "No URLs found" in response.json()["detail"]

    def test_export_campaign_unauthorized(self, client: TestClient):
        """Test that export requires authentication."""
        import uuid

        response = client.get(f"/api/v1/campaigns/{uuid.uuid4()}/export")

        assert response.status_code == 403


@pytest.mark.integration
class TestDeleteCampaign:
    """Test deleting campaigns (DELETE /api/v1/campaigns/{id})."""

    def test_delete_campaign_success(
        self, client: TestClient, auth_headers: dict, db_session: Session, test_user
    ):
        """Test successful campaign deletion."""
        # Create campaign with URLs
        campaign = Campaign(
            name="To Delete",
            original_url="https://example.com",
            csv_columns=["col1"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        # Add URL
        url = URL(
            short_code="del001",
            original_url="https://example.com",
            url_type="campaign",
            campaign_id=campaign.id,
            user_data={"col1": "val1"},
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        campaign_id = campaign.id

        # Delete campaign
        response = client.delete(f"/api/v1/campaigns/{campaign_id}", headers=auth_headers)

        assert response.status_code == 204

        # Verify campaign is deleted
        assert db_session.query(Campaign).filter(Campaign.id == campaign_id).first() is None

        # Verify URLs are also deleted (cascade)
        assert db_session.query(URL).filter(URL.campaign_id == campaign_id).first() is None

    def test_delete_campaign_not_found(self, client: TestClient, auth_headers: dict):
        """Test deleting non-existent campaign."""
        import uuid

        response = client.delete(f"/api/v1/campaigns/{uuid.uuid4()}", headers=auth_headers)

        assert response.status_code == 404

    def test_delete_campaign_unauthorized(self, client: TestClient):
        """Test that deletion requires authentication."""
        import uuid

        response = client.delete(f"/api/v1/campaigns/{uuid.uuid4()}")

        assert response.status_code == 403

    def test_delete_campaign_wrong_user(
        self, client: TestClient, auth_headers: dict, db_session: Session
    ):
        """Test that users can't delete other users' campaigns."""
        from server.core.models import User

        # Create different user
        other_user = User(
            email="other@example.com",
            password_hash="hash",
            is_active=True,
        )
        db_session.add(other_user)
        db_session.flush()

        # Create campaign for other user
        campaign = Campaign(
            name="Other's Campaign",
            original_url="https://example.com",
            csv_columns=["col1"],
            created_by=other_user.id,
        )
        db_session.add(campaign)
        db_session.commit()

        # Try to delete with test_user's auth
        response = client.delete(f"/api/v1/campaigns/{campaign.id}", headers=auth_headers)

        assert response.status_code == 403

        # Verify campaign still exists
        assert db_session.query(Campaign).filter(Campaign.id == campaign.id).first() is not None


@pytest.mark.integration
class TestCampaignURLRedirect:
    """Test that campaign URLs redirect correctly with query params."""

    def test_campaign_url_redirect_with_params(
        self, client: TestClient, db_session: Session, test_user
    ):
        """Test that campaign URLs append user data as query parameters."""
        # Create campaign
        campaign = Campaign(
            name="Redirect Test",
            original_url="https://example.com/landing",
            csv_columns=["firstName", "lastName", "utm_campaign"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        # Create campaign URL
        url = URL(
            short_code="redir001",
            original_url="https://example.com/landing",
            url_type="campaign",
            campaign_id=campaign.id,
            user_data={
                "firstName": "John",
                "lastName": "Doe",
                "utm_campaign": "Q4_2024",
            },
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        # Access the short URL
        response = client.get("/redir001", follow_redirects=False)

        assert response.status_code == 302
        redirect_url = response.headers["location"]

        # Should contain all user_data as query params
        assert "firstName=John" in redirect_url
        assert "lastName=Doe" in redirect_url
        assert "utm_campaign=Q4_2024" in redirect_url
        assert redirect_url.startswith("https://example.com/landing?")

    def test_campaign_url_with_existing_query_params(
        self, client: TestClient, db_session: Session, test_user
    ):
        """Test campaign URL redirect when original URL has query params."""
        # Create campaign with URL that already has query params
        campaign = Campaign(
            name="Query Test",
            original_url="https://example.com/page?existing=param",
            csv_columns=["custom"],
            created_by=test_user.id,
        )
        db_session.add(campaign)
        db_session.flush()

        url = URL(
            short_code="query001",
            original_url="https://example.com/page?existing=param",
            url_type="campaign",
            campaign_id=campaign.id,
            user_data={"custom": "value"},
            created_by=test_user.id,
        )
        db_session.add(url)
        db_session.commit()

        response = client.get("/query001", follow_redirects=False)

        assert response.status_code == 302
        redirect_url = response.headers["location"]

        # Should append with & separator
        assert "existing=param" in redirect_url
        assert "custom=value" in redirect_url
        assert "&custom=value" in redirect_url
