"""Authentication schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class UserRegister(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class Token(BaseModel):
    """Schema for JWT token response."""

    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Schema for user information response."""

    id: UUID
    email: str
    is_active: bool
    created_at: datetime
    api_key: str | None = None
    # Phase 3.13.3 — how this account signs in, for Settings → Account.
    has_password: bool = False
    has_google: bool = False

    class Config:
        from_attributes = True  # Pydantic v2 (was orm_mode in v1)


class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(
        ..., min_length=8, description="Password must be at least 8 characters"
    )


class SetPasswordRequest(BaseModel):
    """Phase 3.13.3 — set or replace the password (PUT /auth/password)."""

    new_password: str = Field(
        ..., min_length=8, description="Password must be at least 8 characters"
    )
    current_password: str | None = Field(
        None,
        description=(
            "The password to replace. Required when the account has no Google sign-in; "
            "without it, the session must be at most 10 minutes old."
        ),
    )


class GoogleCodeExchange(BaseModel):
    """Phase 3.13.2 — the one-time code the Google callback put in the frontend's URL."""

    code: str = Field(..., min_length=1, max_length=128)


class APIKeyResponse(BaseModel):
    """Schema for API key response."""

    api_key: str
    scope: str = "full_access"  # Phase 3.9.6 — only enforced value at launch
