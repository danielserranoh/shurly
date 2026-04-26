"""Tests for authentication endpoints."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from server.core.models import User


class TestUserRegistration:
    """Test user registration endpoint."""

    def test_register_success(self, client: TestClient):
        """Test successful user registration."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "newuser@example.com", "password": "password123"},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "id" in data
        assert "password" not in data
        assert "password_hash" not in data

    def test_register_duplicate_email(self, client: TestClient, test_user: User):
        """Test registration with existing email."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": test_user.email, "password": "password123"},
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"].lower()

    def test_register_invalid_email(self, client: TestClient):
        """Test registration with invalid email format."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "not-an-email", "password": "password123"},
        )
        assert response.status_code == 422  # Validation error

    def test_register_short_password(self, client: TestClient):
        """Test registration with password less than 8 characters."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "short"},
        )
        assert response.status_code == 422  # Validation error

    def test_register_missing_email(self, client: TestClient):
        """Test registration without email."""
        response = client.post(
            "/api/v1/auth/register",
            json={"password": "password123"},
        )
        assert response.status_code == 422

    def test_register_missing_password(self, client: TestClient):
        """Test registration without password."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com"},
        )
        assert response.status_code == 422


class TestUserLogin:
    """Test user login endpoint."""

    def test_login_success(self, client: TestClient, test_user: User):
        """Test successful login."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "test123"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20  # JWT should be fairly long

    def test_login_wrong_password(self, client: TestClient, test_user: User):
        """Test login with incorrect password."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "wrongpassword"},
        )
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    def test_login_nonexistent_user(self, client: TestClient):
        """Test login with email that doesn't exist."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "password123"},
        )
        assert response.status_code == 401

    def test_login_invalid_email_format(self, client: TestClient):
        """Test login with malformed email."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "password123"},
        )
        assert response.status_code == 422  # Validation error

    def test_login_empty_password(self, client: TestClient, test_user: User):
        """Test login with empty password."""
        response = client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": ""},
        )
        assert response.status_code == 401


class TestGetCurrentUser:
    """Test get current user endpoint."""

    def test_get_current_user_success(self, client: TestClient, auth_headers: dict, test_user: User):
        """Test getting current user info with valid token."""
        response = client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user.email
        assert data["id"] == str(test_user.id)  # UUID is serialized as string
        assert "password" not in data
        assert "password_hash" not in data

    def test_get_current_user_no_token(self, client: TestClient):
        """Test getting current user without authentication."""
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401  # HTTPBearer returns 401 when no credentials

    def test_get_current_user_invalid_token(self, client: TestClient):
        """Test getting current user with invalid token."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid-token-12345"},
        )
        assert response.status_code == 401

    def test_get_current_user_malformed_header(self, client: TestClient):
        """Test getting current user with malformed auth header."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "NotBearer token123"},
        )
        assert response.status_code == 401  # HTTPBearer returns 401 for malformed header


class TestChangePassword:
    """Test password change endpoint."""

    def test_change_password_success(self, client: TestClient, auth_headers: dict, test_user: User):
        """Test successful password change."""
        response = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": "test123",
                "new_password": "newpassword123",
            },
        )
        assert response.status_code == 200
        assert "success" in response.json()["message"].lower()

        # Verify can login with new password
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "newpassword123"},
        )
        assert login_response.status_code == 200

        # Verify old password doesn't work
        old_login = client.post(
            "/api/v1/auth/login",
            json={"email": test_user.email, "password": "test123"},
        )
        assert old_login.status_code == 401

    def test_change_password_wrong_current_password(self, client: TestClient, auth_headers: dict):
        """Test password change with incorrect current password."""
        response = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": "wrongpassword",
                "new_password": "newpassword123",
            },
        )
        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"].lower()

    def test_change_password_unauthorized(self, client: TestClient):
        """Test password change without authentication."""
        response = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "test123",
                "new_password": "newpassword123",
            },
        )
        assert response.status_code == 401  # HTTPBearer returns 401 when no credentials

    def test_change_password_short_new_password(self, client: TestClient, auth_headers: dict):
        """Test password change with new password < 8 characters."""
        response = client.post(
            "/api/v1/auth/change-password",
            headers=auth_headers,
            json={
                "current_password": "test123",
                "new_password": "short",
            },
        )
        assert response.status_code == 422  # Validation error


class TestAPIKeyManagement:
    """Test API key generation and revocation."""

    def test_generate_api_key_success(self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User):
        """Test successful API key generation."""
        response = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "api_key" in data
        assert len(data["api_key"]) > 20  # Should be reasonably long

        # Verify API key is stored in database
        db_session.refresh(test_user)
        assert test_user.api_key == data["api_key"]

    def test_generate_api_key_replaces_existing(self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User):
        """Test that generating new API key replaces the old one."""
        # Generate first key
        response1 = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
        assert response1.status_code == 200
        first_key = response1.json()["api_key"]

        # Generate second key
        response2 = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
        assert response2.status_code == 200
        second_key = response2.json()["api_key"]

        # Keys should be different
        assert first_key != second_key

        # Database should have second key
        db_session.refresh(test_user)
        assert test_user.api_key == second_key

    def test_generate_api_key_unauthorized(self, client: TestClient):
        """Test API key generation without authentication."""
        response = client.post("/api/v1/auth/api-key/generate")
        assert response.status_code == 401  # HTTPBearer returns 401 when no credentials

    def test_revoke_api_key_success(self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User):
        """Test successful API key revocation."""
        # First generate a key
        generate_response = client.post("/api/v1/auth/api-key/generate", headers=auth_headers)
        assert generate_response.status_code == 200
        db_session.refresh(test_user)
        assert test_user.api_key is not None

        # Now revoke it
        revoke_response = client.delete("/api/v1/auth/api-key", headers=auth_headers)
        assert revoke_response.status_code == 200
        assert "revoked" in revoke_response.json()["message"].lower()

        # Verify API key is removed from database
        db_session.refresh(test_user)
        assert test_user.api_key is None

    def test_revoke_api_key_when_none_exists(self, client: TestClient, auth_headers: dict, db_session: Session, test_user: User):
        """Test revoking API key when user has no API key."""
        # Ensure no API key exists
        assert test_user.api_key is None

        # Should still succeed
        response = client.delete("/api/v1/auth/api-key", headers=auth_headers)
        assert response.status_code == 200

    def test_revoke_api_key_unauthorized(self, client: TestClient):
        """Test API key revocation without authentication."""
        response = client.delete("/api/v1/auth/api-key")
        assert response.status_code == 401  # HTTPBearer returns 401 when no credentials


class TestAuthenticationEdgeCases:
    """Test edge cases and error scenarios."""

    def test_special_characters_in_password(self, client: TestClient):
        """Test registration with special characters in password."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "P@ssw0rd!#$%^"},
        )
        assert response.status_code == 201

        # Verify can login
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "P@ssw0rd!#$%^"},
        )
        assert login_response.status_code == 200

    def test_unicode_in_password(self, client: TestClient):
        """Test registration with unicode characters in password (within bcrypt 72-byte limit)."""
        # Using a shorter unicode password that stays under 72 bytes
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "пароль123"},  # Russian + number
        )
        assert response.status_code == 201

        # Verify can login
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "пароль123"},
        )
        assert login_response.status_code == 200

    def test_register_with_spaces_in_password(self, client: TestClient):
        """Test registration with spaces in password."""
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "test@example.com", "password": "password with spaces"},
        )
        assert response.status_code == 201

        # Verify can login with exact password
        login_response = client.post(
            "/api/v1/auth/login",
            json={"email": "test@example.com", "password": "password with spaces"},
        )
        assert login_response.status_code == 200
