"""Tests for URL tagging functionality."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import Tag, URL, URLType, Campaign


@pytest.mark.integration
class TestURLTagging:
    """Test URL tagging functionality."""

    def test_add_tags_to_url(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Can add tags to URL."""
        # Create tags
        tag1 = Tag(name="email", display_name="email", color="blue-500", is_predefined=True)
        tag2 = Tag(name="campaign", display_name="Campaign", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])

        # Create URL
        url = URL(
            short_code="test123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        db_session.add(url)
        db_session.commit()

        # Add tags
        response = client.patch(
            f"/api/v1/urls/test123/tags",
            json={"tag_ids": [str(tag1.id), str(tag2.id)]},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["tags"]) == 2
        tag_names = [tag["name"] for tag in data["tags"]]
        assert "email" in tag_names
        assert "campaign" in tag_names

    def test_replace_url_tags(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Updating tags replaces existing tags."""
        # Create tags
        tag1 = Tag(name="tag1", display_name="Tag1", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="tag2", display_name="Tag2", color="gray-500", created_by=test_user.id)
        tag3 = Tag(name="tag3", display_name="Tag3", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2, tag3])

        # Create URL with tag1
        url = URL(
            short_code="test123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        url.tags.append(tag1)
        db_session.add(url)
        db_session.commit()

        # Replace with tag2 and tag3
        response = client.patch(
            f"/api/v1/urls/test123/tags",
            json={"tag_ids": [str(tag2.id), str(tag3.id)]},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["tags"]) == 2
        tag_names = [tag["name"] for tag in data["tags"]]
        assert "tag1" not in tag_names
        assert "tag2" in tag_names
        assert "tag3" in tag_names

    def test_tag_url_with_invalid_tag_id(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Tagging with non-existent tag ID fails."""
        import uuid

        # Create URL
        url = URL(
            short_code="test123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        db_session.add(url)
        db_session.commit()

        # Try to add fake tag
        fake_id = uuid.uuid4()
        response = client.patch(
            f"/api/v1/urls/test123/tags",
            json={"tag_ids": [str(fake_id)]},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "not found" in response.json()["detail"].lower()

    def test_tag_url_not_found(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Tagging non-existent URL returns 404."""
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)
        db_session.commit()

        response = client.patch(
            f"/api/v1/urls/nonexistent/tags",
            json={"tag_ids": [str(tag.id)]},
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_tag_url_wrong_owner(self, client: TestClient, auth_headers: dict, db_session: Session):
        """Cannot tag another user's URL."""
        from server.core.models import User as UserModel

        # Create another user
        other_user = UserModel(
            email="other@example.com",
            password_hash="hashed",
            is_active=True
        )
        db_session.add(other_user)
        db_session.flush()

        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=other_user.id)
        db_session.add(tag)

        # Create URL owned by other user
        url = URL(
            short_code="notmine",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=other_user.id
        )
        db_session.add(url)
        db_session.commit()

        # Try to tag with test_user's auth
        response = client.patch(
            f"/api/v1/urls/notmine/tags",
            json={"tag_ids": [str(tag.id)]},
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_bulk_tag_urls(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Can bulk tag multiple URLs."""
        # Create tag
        tag = Tag(name="bulk", display_name="Bulk", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URLs
        url1 = URL(short_code="url1", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url2 = URL(short_code="url2", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Bulk tag
        response = client.post(
            "/api/v1/urls/bulk/tags",
            json={
                "short_codes": ["url1", "url2"],
                "tag_ids": [str(tag.id)]
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["updated"] == 2

        # Verify tags applied
        db_session.refresh(url1)
        db_session.refresh(url2)
        assert len(url1.tags) == 1
        assert len(url2.tags) == 1

    def test_bulk_tag_adds_to_existing(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Bulk tagging adds to existing tags (doesn't replace)."""
        # Create tags
        tag1 = Tag(name="tag1", display_name="Tag1", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="tag2", display_name="Tag2", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])

        # Create URL with tag1
        url = URL(short_code="url1", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url.tags.append(tag1)
        db_session.add(url)
        db_session.commit()

        # Bulk add tag2
        response = client.post(
            "/api/v1/urls/bulk/tags",
            json={
                "short_codes": ["url1"],
                "tag_ids": [str(tag2.id)]
            },
            headers=auth_headers
        )
        assert response.status_code == 200

        # Verify both tags present
        db_session.refresh(url)
        assert len(url.tags) == 2

    def test_bulk_tag_skips_other_users_urls(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Bulk tagging only affects user's own URLs."""
        from server.core.models import User as UserModel

        # Create another user
        other_user = UserModel(
            email="other@example.com",
            password_hash="hashed",
            is_active=True
        )
        db_session.add(other_user)
        db_session.flush()

        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create user's URL
        url1 = URL(short_code="mine", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        # Create other user's URL
        url2 = URL(short_code="theirs", original_url="https://b.com", url_type=URLType.STANDARD, created_by=other_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Try to bulk tag both
        response = client.post(
            "/api/v1/urls/bulk/tags",
            json={
                "short_codes": ["mine", "theirs"],
                "tag_ids": [str(tag.id)]
            },
            headers=auth_headers
        )
        assert response.status_code == 200
        # Only 1 updated (user's own URL)
        assert response.json()["updated"] == 1

        # Verify only user's URL was tagged
        db_session.refresh(url1)
        db_session.refresh(url2)
        assert len(url1.tags) == 1
        assert len(url2.tags) == 0


@pytest.mark.integration
class TestURLFiltering:
    """Test filtering URLs by tags."""

    def test_filter_urls_by_single_tag(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Filter URLs by tag."""
        # Create tag
        tag = Tag(name="filter", display_name="Filter", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URLs (one with tag, one without)
        url1 = URL(short_code="with", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url1.tags.append(tag)
        url2 = URL(short_code="without", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Filter
        response = client.get(f"/api/v1/urls?tags={tag.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["urls"][0]["short_code"] == "with"

    def test_filter_urls_by_multiple_tags_or(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Filter URLs by multiple tags (OR logic)."""
        # Create tags
        tag1 = Tag(name="tag1", display_name="Tag1", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="tag2", display_name="Tag2", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])

        # Create URLs
        url1 = URL(short_code="url1", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url1.tags.append(tag1)

        url2 = URL(short_code="url2", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url2.tags.append(tag2)

        url3 = URL(short_code="url3", original_url="https://c.com", url_type=URLType.STANDARD, created_by=test_user.id)
        # No tags

        db_session.add_all([url1, url2, url3])
        db_session.commit()

        # Filter with OR (default)
        response = client.get(f"/api/v1/urls?tags={tag1.id},{tag2.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        codes = [url["short_code"] for url in data["urls"]]
        assert "url1" in codes
        assert "url2" in codes
        assert "url3" not in codes

    def test_filter_urls_by_multiple_tags_and(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Filter URLs by multiple tags (AND logic)."""
        # Create tags
        tag1 = Tag(name="tag1", display_name="Tag1", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="tag2", display_name="Tag2", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])

        # Create URLs
        url1 = URL(short_code="url1", original_url="https://a.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url1.tags.extend([tag1, tag2])  # Has both tags

        url2 = URL(short_code="url2", original_url="https://b.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url2.tags.append(tag1)  # Has only tag1

        db_session.add_all([url1, url2])
        db_session.commit()

        # Filter with AND
        response = client.get(f"/api/v1/urls?tags={tag1.id},{tag2.id}&tag_filter=all", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["urls"][0]["short_code"] == "url1"

    def test_url_response_includes_tags(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """URL responses include tags."""
        # Create tag
        tag = Tag(name="test", display_name="Test", color="blue-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URL with tag
        url = URL(short_code="test", original_url="https://example.com", url_type=URLType.STANDARD, created_by=test_user.id)
        url.tags.append(tag)
        db_session.add(url)
        db_session.commit()

        # Get URL list
        response = client.get("/api/v1/urls", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Find our URL
        test_url = next((u for u in data["urls"] if u["short_code"] == "test"), None)
        assert test_url is not None
        assert len(test_url["tags"]) == 1
        assert test_url["tags"][0]["name"] == "test"
        assert test_url["tags"][0]["display_name"] == "Test"
        assert test_url["tags"][0]["color"] == "blue-500"


@pytest.mark.integration
class TestCampaignTagging:
    """Test campaign tagging functionality."""

    def test_tag_campaign(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Can tag campaign."""
        # Create tag
        tag = Tag(name="campaign-tag", display_name="Campaign Tag", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create campaign
        campaign = Campaign(
            name="Test Campaign",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id
        )
        db_session.add(campaign)
        db_session.commit()

        # Tag campaign
        response = client.patch(
            f"/api/v1/campaigns/{campaign.id}/tags",
            json={"tag_ids": [str(tag.id)]},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["tags"]) == 1
        assert data["tags"][0]["name"] == "campaign-tag"

    def test_campaign_tags_apply_to_urls(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Campaign tags are applied to all campaign URLs."""
        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create campaign with URLs
        campaign = Campaign(
            name="Test Campaign",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id
        )
        db_session.add(campaign)
        db_session.flush()

        # Create campaign URLs
        url1 = URL(short_code="url1", original_url="https://a.com", url_type=URLType.CAMPAIGN, campaign_id=campaign.id, created_by=test_user.id)
        url2 = URL(short_code="url2", original_url="https://b.com", url_type=URLType.CAMPAIGN, campaign_id=campaign.id, created_by=test_user.id)
        db_session.add_all([url1, url2])
        db_session.commit()

        # Tag campaign
        client.patch(
            f"/api/v1/campaigns/{campaign.id}/tags",
            json={"tag_ids": [str(tag.id)]},
            headers=auth_headers
        )

        # Verify tags applied to URLs
        db_session.refresh(url1)
        db_session.refresh(url2)
        assert len(url1.tags) == 1
        assert len(url2.tags) == 1

    def test_campaign_response_includes_tags(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Campaign responses include tags."""
        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create campaign with tag
        campaign = Campaign(
            name="Test Campaign",
            original_url="https://example.com",
            csv_columns=["name"],
            created_by=test_user.id
        )
        campaign.tags.append(tag)
        db_session.add(campaign)
        db_session.commit()

        # Get campaign list
        response = client.get("/api/v1/campaigns", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Find our campaign
        test_campaign = next((c for c in data["campaigns"] if c["name"] == "Test Campaign"), None)
        assert test_campaign is not None
        assert len(test_campaign["tags"]) == 1
        assert test_campaign["tags"][0]["name"] == "test"
