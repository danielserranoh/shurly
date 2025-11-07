"""Schemas for URL shortening."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.core.models.url import URLType
from server.utils.url import is_valid_url


class URLCreate(BaseModel):
    """Schema for creating a standard short URL."""

    url: str = Field(..., description="The original URL to shorten")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v


class URLCustomCreate(BaseModel):
    """Schema for creating a custom short URL."""

    url: str = Field(..., description="The original URL to shorten")
    custom_code: str = Field(..., description="Custom short code (3-20 characters)")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v


class URLResponse(BaseModel):
    """Schema for URL response."""

    id: UUID
    short_code: str
    short_url: str
    original_url: str
    url_type: URLType
    created_at: datetime
    warning: str | None = None  # For custom URLs when code was modified

    model_config = {"from_attributes": True}


class URLListResponse(BaseModel):
    """Schema for list of URLs."""

    urls: list[URLResponse]
    total: int
