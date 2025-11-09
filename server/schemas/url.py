"""Schemas for URL shortening."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.core.models.url import URLType
from server.utils.url import is_valid_url

if TYPE_CHECKING:
    from server.schemas.tag import TagResponse


class URLCreate(BaseModel):
    """Schema for creating a standard short URL."""

    url: str = Field(..., description="The original URL to shorten")
    title: str | None = Field(None, max_length=255, description="Optional user-friendly title")
    forward_parameters: bool = Field(True, description="Forward query parameters to destination")

    # Open Graph fields (optional)
    og_title: str | None = Field(None, max_length=255, description="Custom Open Graph title")
    og_description: str | None = Field(None, description="Custom Open Graph description")
    og_image_url: str | None = Field(None, description="Custom Open Graph image URL")

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

    # Tags
    tags: list["TagResponse"] = []

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
