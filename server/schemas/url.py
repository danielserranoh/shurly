"""Schemas for URL shortening."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.core.models.url import URLType
from server.utils.url import is_valid_url

if TYPE_CHECKING:
    pass  # Keep for future type checking needs

# Import for runtime use (model_rebuild needs it)
from server.schemas.tag import TagResponse  # noqa: E402


class URLCreate(BaseModel):
    """Schema for creating a standard short URL."""

    url: str = Field(..., description="The original URL to shorten")
    title: str | None = Field(None, max_length=255, description="Optional user-friendly title")
    forward_parameters: bool = Field(True, description="Forward query parameters to destination")

    # Open Graph fields (optional)
    og_title: str | None = Field(None, max_length=255, description="Custom Open Graph title")
    og_description: str | None = Field(None, description="Custom Open Graph description")
    og_image_url: str | None = Field(None, description="Custom Open Graph image URL")

    # Phase 3.9.2 — validity window and visit cap (all optional, NULL = no constraint)
    valid_since: datetime | None = Field(None, description="URL becomes active at this UTC timestamp")
    valid_until: datetime | None = Field(None, description="URL stops being active at this UTC timestamp")
    max_visits: int | None = Field(None, ge=1, description="Hard cap on real visits before returning 410 Gone")

    # Phase 3.9.4 — default-deny crawlability
    crawlable: bool = Field(False, description="Allow this short URL in robots.txt (default: deny)")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v


class URLCustomCreate(BaseModel):
    """Schema for creating a custom short URL."""

    url: str = Field(..., description="The original URL to shorten")
    custom_code: str = Field(..., description="Custom short code (3-20 characters)")
    title: str | None = Field(None, max_length=255, description="Optional user-friendly title")
    forward_parameters: bool = Field(True, description="Forward query parameters to destination")

    # Open Graph fields (optional)
    og_title: str | None = Field(None, max_length=255, description="Custom Open Graph title")
    og_description: str | None = Field(None, description="Custom Open Graph description")
    og_image_url: str | None = Field(None, description="Custom Open Graph image URL")

    # Phase 3.9.2 — validity window and visit cap
    valid_since: datetime | None = Field(None, description="URL becomes active at this UTC timestamp")
    valid_until: datetime | None = Field(None, description="URL stops being active at this UTC timestamp")
    max_visits: int | None = Field(None, ge=1, description="Hard cap on real visits before returning 410 Gone")

    # Phase 3.9.4 — default-deny crawlability
    crawlable: bool = Field(False, description="Allow this short URL in robots.txt (default: deny)")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v


class URLUpdate(BaseModel):
    """Schema for updating a URL."""

    title: str | None = Field(None, max_length=255, description="Update URL title")
    original_url: str | None = Field(None, description="Update destination URL")
    forward_parameters: bool | None = Field(None, description="Update forward parameters setting")

    # Open Graph fields
    og_title: str | None = Field(None, max_length=255, description="Update Open Graph title")
    og_description: str | None = Field(None, description="Update Open Graph description")
    og_image_url: str | None = Field(None, description="Update Open Graph image URL")

    # Phase 3.9.2 — validity window and visit cap (passing null clears the field)
    valid_since: datetime | None = Field(None, description="Update activation timestamp (null clears)")
    valid_until: datetime | None = Field(None, description="Update expiration timestamp (null clears)")
    max_visits: int | None = Field(None, ge=1, description="Update visit cap (null clears)")

    # Phase 3.9.4 — toggle crawlability
    crawlable: bool | None = Field(None, description="Allow this short URL in robots.txt")

    @field_validator("original_url")
    @classmethod
    def validate_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("og_image_url")
    @classmethod
    def validate_og_image_url(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid image URL format. Must be a valid http or https URL.")
        return v

    model_config = {"extra": "forbid"}  # Prevent updating immutable fields


class URLResponse(BaseModel):
    """Schema for URL response."""

    id: UUID
    short_code: str
    short_url: str | None = None  # Computed field, set after validation
    original_url: str
    url_type: URLType
    title: str | None = None
    forward_parameters: bool = True

    # Open Graph fields
    og_title: str | None = None
    og_description: str | None = None
    og_image_url: str | None = None
    og_fetched_at: datetime | None = None

    # Analytics
    last_click_at: datetime | None = None

    # Phase 3.9.2 — validity window and visit cap
    valid_since: datetime | None = None
    valid_until: datetime | None = None
    max_visits: int | None = None

    # Phase 3.9.4 — crawlability flag
    crawlable: bool = False

    # Tags
    tags: list[TagResponse] = []

    # Audit fields
    created_at: datetime
    updated_at: datetime
    warning: str | None = None  # For custom URLs when code was modified

    model_config = {"from_attributes": True}


class URLListResponse(BaseModel):
    """Schema for list of URLs."""

    urls: list[URLResponse]
    total: int


class OpenGraphMetadataResponse(BaseModel):
    """Response for Open Graph preview endpoint."""

    og_title: str | None
    og_description: str | None
    og_image_url: str | None
    og_url: str
    has_custom_preview: bool
    fetched_at: datetime | None
