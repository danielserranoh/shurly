"""Authentication schemas."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator
from pydantic_core import PydanticCustomError

from server.core.auth import BCRYPT_MAX_BYTES
from server.schemas.datetimes import UtcDateTime
from server.schemas.profile import ProfileResponse


def check_password_length(password: str) -> str:
    """A new password fits what bcrypt reads, 72 bytes: past them, its end would be ignored.
    Signing in has no such check, so a password set longer before still works."""
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        # Its own error type, so the message is read as it is, without "Value error, " before it.
        raise PydanticCustomError(
            "password_too_long",
            "Too long: a password can be at most 72 bytes. That's 72 characters of plain text, "
            "and fewer with accented letters or emoji, which take more than one byte each.",
        )
    return password


class UserRegister(BaseModel):
    """Schema for user registration."""

    email: EmailStr
    password: str = Field(
        ...,
        min_length=8,
        description="Password must be at least 8 characters, and at most 72 bytes",
    )

    _fits_bcrypt = field_validator("password")(check_password_length)


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
    created_at: UtcDateTime
    # Phase 6.3 — whether there's an API key and how it starts, never the key: it's
    # shown once, by /api-key/generate. (This answer reaches an assistant through the
    # MCP's get_current_user_info.)
    has_api_key: bool = False
    api_key_prefix: str | None = None
    # Phase 3.13.3 — how this account signs in, for Settings → Account.
    has_password: bool = False
    has_google: bool = False
    # Phase 3.12 — always there; an account that never saved one reads as empty.
    profile: ProfileResponse = Field(default_factory=ProfileResponse)

    @field_validator("profile", mode="before")
    @classmethod
    def _no_profile_is_an_empty_one(cls, value):
        return ProfileResponse() if value is None else value

    class Config:
        from_attributes = True  # Pydantic v2 (was orm_mode in v1)


class ChangePasswordRequest(BaseModel):
    """Schema for changing password."""

    current_password: str
    new_password: str = Field(
        ...,
        min_length=8,
        description="Password must be at least 8 characters, and at most 72 bytes",
    )

    _fits_bcrypt = field_validator("new_password")(check_password_length)


class SetPasswordRequest(BaseModel):
    """Phase 3.13.3 — set or replace the password (PUT /auth/password)."""

    new_password: str = Field(
        ...,
        min_length=8,
        description="Password must be at least 8 characters, and at most 72 bytes",
    )
    current_password: str | None = Field(
        None,
        description=(
            "The password to replace. Required when the account has no Google sign-in; "
            "without it, the session must be at most 10 minutes old."
        ),
    )

    _fits_bcrypt = field_validator("new_password")(check_password_length)


class GoogleCodeExchange(BaseModel):
    """Phase 3.13.2 — the one-time code the Google callback put in the frontend's URL."""

    code: str = Field(..., min_length=1, max_length=128)


class APIKeyResponse(BaseModel):
    """Schema for API key response: the only time the key itself is shown."""

    api_key: str
    scope: str = "full_access"  # Phase 3.9.6 — only enforced value at launch
