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

    class Config:
        from_attributes = True  # Pydantic v2 (was orm_mode in v1)


class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(..., min_length=8, description="Password must be at least 8 characters")


class APIKeyResponse(BaseModel):
    """Schema for API key response."""

    api_key: str
