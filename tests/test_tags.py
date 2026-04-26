"""Tests for tag management functionality."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import Tag, URL, URLType, Campaign


@pytest.mark.integration
class TestTagCRUD:
    """Test tag CRUD operations."""

    def test_list_tags_includes_predefined(self, client: TestClient, auth_headers: dict, init_predefined_tags):
        """Predefined tags should be returned."""
        response = client.get("/api/v1/tags", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        # Check for at least one predefined tag
        predefined_tags = [tag for tag in data["tags"] if tag["is_predefined"]]
        assert len(predefined_tags) > 0
        # Check for specific predefined tag
        tag_names = [tag["name"] for tag in data["tags"]]
        assert "email" in tag_names

    def test_list_tags_shows_usage_count(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Tags should show usage count."""
        # Create a tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URL with tag
        url = URL(
            short_code="tagged",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        url.tags.append(tag)
        db_session.add(url)
        db_session.commit()

        response = client.get("/api/v1/tags", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        # Find the test tag
        test_tag = next((t for t in data["tags"] if t["name"] == "test"), None)
        assert test_tag is not None
        assert test_tag["usage_count"] == 1

    def test_search_tags_by_name(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Can search tags by name prefix."""
        # Create tags
        tag1 = Tag(name="marketing", display_name="Marketing", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="sales", display_name="Sales", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])
        db_session.commit()

        response = client.get("/api/v1/tags?search=mark", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()

        tag_names = [tag["name"] for tag in data["tags"]]
        assert "marketing" in tag_names
        assert "sales" not in tag_names

    def test_filter_tags_by_type(self, client: TestClient, auth_headers: dict, init_predefined_tags):
        """Can filter tags by predefined/user-created."""
        # Get predefined only
        response = client.get("/api/v1/tags?is_predefined=true", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert all(tag["is_predefined"] for tag in data["tags"])

        # Get user tags only
        response = client.get("/api/v1/tags?is_predefined=false", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert all(not tag["is_predefined"] for tag in data["tags"])

    def test_create_user_tag(self, client: TestClient, auth_headers: dict):
        """User can create custom tag."""
        response = client.post(
            "/api/v1/tags",
            json={"name": "My Campaign"},
            headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "my campaign"  # lowercase
        assert data["display_name"] == "My Campaign"
        assert data["is_predefined"] is False
        assert data["color"] == "gray-500"
        assert data["usage_count"] == 0

    def test_create_tag_case_insensitive_duplicate(self, client: TestClient, auth_headers: dict):
        """Creating tag with different case should fail."""
        client.post("/api/v1/tags", json={"name": "Test"}, headers=auth_headers)
        response = client.post(
            "/api/v1/tags",
            json={"name": "test"},  # Same, different case
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_create_tag_too_long(self, client: TestClient, auth_headers: dict):
        """Tag name exceeding 30 chars should fail."""
        long_name = "a" * 31
        response = client.post(
            "/api/v1/tags",
            json={"name": long_name},
            headers=auth_headers
        )
        assert response.status_code == 422  # Pydantic validation

    def test_create_tag_empty_name(self, client: TestClient, auth_headers: dict):
        """Tag name cannot be empty."""
        response = client.post(
            "/api/v1/tags",
            json={"name": "   "},
            headers=auth_headers
        )
        assert response.status_code == 422

    def test_create_tag_with_emoji(self, client: TestClient, auth_headers: dict):
        """Tags can contain emojis."""
        response = client.post(
            "/api/v1/tags",
            json={"name": "🚀 Launch"},
            headers=auth_headers
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "🚀 launch"
        assert data["display_name"] == "🚀 Launch"

    def test_create_tag_requires_auth(self, client: TestClient):
        """Creating tag requires authentication."""
        response = client.post("/api/v1/tags", json={"name": "Test"})
        assert response.status_code == 401

    def test_update_user_tag(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """User can rename their tag."""
        # Create tag
        tag = Tag(
            name="oldname",
            display_name="OldName",
            color="gray-500",
            created_by=test_user.id
        )
        db_session.add(tag)
        db_session.commit()

        # Update
        response = client.patch(
            f"/api/v1/tags/{tag.id}",
            json={"name": "NewName"},
            headers=auth_headers
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "newname"
        assert data["display_name"] == "NewName"

    def test_update_tag_checks_uniqueness(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Cannot rename tag to existing name."""
        # Create two tags
        tag1 = Tag(name="tag1", display_name="Tag1", color="gray-500", created_by=test_user.id)
        tag2 = Tag(name="tag2", display_name="Tag2", color="gray-500", created_by=test_user.id)
        db_session.add_all([tag1, tag2])
        db_session.commit()

        # Try to rename tag1 to tag2
        response = client.patch(
            f"/api/v1/tags/{tag1.id}",
            json={"name": "Tag2"},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()

    def test_update_predefined_tag_forbidden(self, client: TestClient, auth_headers: dict, db_session: Session, init_predefined_tags):
        """Cannot update predefined tags."""
        # Get a predefined tag
        tag = db_session.query(Tag).filter(Tag.is_predefined == True).first()
        assert tag is not None

        response = client.patch(
            f"/api/v1/tags/{tag.id}",
            json={"name": "NewName"},
            headers=auth_headers
        )
        assert response.status_code == 400
        assert "predefined" in response.json()["detail"].lower()

    def test_update_tag_not_found(self, client: TestClient, auth_headers: dict):
        """Updating non-existent tag returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = client.patch(
            f"/api/v1/tags/{fake_id}",
            json={"name": "Test"},
            headers=auth_headers
        )
        assert response.status_code == 404

    def test_delete_user_tag(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """User can delete their tag."""
        tag = Tag(
            name="deleteme",
            display_name="DeleteMe",
            color="gray-500",
            created_by=test_user.id
        )
        db_session.add(tag)
        db_session.commit()
        tag_id = tag.id

        response = client.delete(f"/api/v1/tags/{tag_id}", headers=auth_headers)
        assert response.status_code == 204

        # Verify deleted
        assert db_session.query(Tag).filter(Tag.id == tag_id).first() is None

    def test_delete_tag_removes_from_urls(self, client: TestClient, auth_headers: dict, db_session: Session, test_user):
        """Deleting tag removes it from all URLs."""
        # Create tag
        tag = Tag(name="test", display_name="Test", color="gray-500", created_by=test_user.id)
        db_session.add(tag)

        # Create URL with tag
        url = URL(
            short_code="abc123",
            original_url="https://example.com",
            url_type=URLType.STANDARD,
            created_by=test_user.id
        )
        url.tags.append(tag)
        db_session.add(url)
        db_session.commit()

        # Delete tag
        client.delete(f"/api/v1/tags/{tag.id}", headers=auth_headers)

        # Verify URL has no tags
        db_session.refresh(url)
        assert len(url.tags) == 0

    def test_delete_predefined_tag_forbidden(self, client: TestClient, auth_headers: dict, db_session: Session, init_predefined_tags):
        """Cannot delete predefined tags."""
        # Get a predefined tag
        tag = db_session.query(Tag).filter(Tag.is_predefined == True).first()
        assert tag is not None

        response = client.delete(f"/api/v1/tags/{tag.id}", headers=auth_headers)
        assert response.status_code == 400
        assert "predefined" in response.json()["detail"].lower()

    def test_delete_tag_not_found(self, client: TestClient, auth_headers: dict):
        """Deleting non-existent tag returns 404."""
        import uuid
        fake_id = uuid.uuid4()
        response = client.delete(f"/api/v1/tags/{fake_id}", headers=auth_headers)
        assert response.status_code == 404


@pytest.mark.integration
class TestTagInitialization:
    """Test predefined tag initialization."""

    def test_predefined_tags_initialized(self, db_session: Session):
        """Predefined tags should be created on startup."""
        from server.utils.tags import initialize_predefined_tags

        # Clear existing tags first
        db_session.query(Tag).delete()
        db_session.commit()

        initialize_predefined_tags(db_session)

        tags = db_session.query(Tag).filter(Tag.is_predefined == True).all()
        assert len(tags) > 0

        # Check for specific tags
        email_tag = db_session.query(Tag).filter(Tag.name == "email").first()
        assert email_tag is not None
        assert email_tag.color == "blue-500"
        assert email_tag.is_predefined is True

    def test_predefined_tags_idempotent(self, db_session: Session):
        """Running initialization twice should not create duplicates."""
        from server.utils.tags import initialize_predefined_tags

        initialize_predefined_tags(db_session)
        count1 = db_session.query(Tag).filter(Tag.is_predefined == True).count()

        initialize_predefined_tags(db_session)
        count2 = db_session.query(Tag).filter(Tag.is_predefined == True).count()

        assert count1 == count2

    def test_initialization_updates_colors(self, db_session: Session):
        """Initialization updates colors if config changes."""
        from server.utils.tags import initialize_predefined_tags

        # Create tag with different color
        tag = Tag(name="email", display_name="email", color="red-500", is_predefined=True)
        db_session.add(tag)
        db_session.commit()

        # Run initialization
        initialize_predefined_tags(db_session)

        # Verify color updated
        db_session.refresh(tag)
        assert tag.color == "blue-500"  # Should match config


@pytest.mark.integration
class TestTagValidation:
    """Test tag name validation utilities."""

    def test_normalize_tag_name(self):
        """Tag names are normalized to lowercase."""
        from server.utils.tags import normalize_tag_name

        assert normalize_tag_name("Test") == "test"
        assert normalize_tag_name("  Test  ") == "test"
        assert normalize_tag_name("TEST") == "test"

    def test_validate_tag_name_success(self):
        """Valid tag names pass validation."""
        from server.utils.tags import validate_tag_name

        is_valid, error = validate_tag_name("Valid Tag")
        assert is_valid is True
        assert error == ""

        is_valid, error = validate_tag_name("🚀 Launch")
        assert is_valid is True

    def test_validate_tag_name_empty(self):
        """Empty tag names fail validation."""
        from server.utils.tags import validate_tag_name

        is_valid, error = validate_tag_name("")
        assert is_valid is False
        assert "empty" in error.lower()

        is_valid, error = validate_tag_name("   ")
        assert is_valid is False

    def test_validate_tag_name_too_long(self):
        """Tag names over 30 chars fail validation."""
        from server.utils.tags import validate_tag_name

        long_name = "a" * 31
        is_valid, error = validate_tag_name(long_name)
        assert is_valid is False
        assert "30" in error

    def test_validate_tag_name_control_chars(self):
        """Tag names with control characters fail validation."""
        from server.utils.tags import validate_tag_name

        is_valid, error = validate_tag_name("Test\n")
        assert is_valid is False
        assert "invalid" in error.lower()
