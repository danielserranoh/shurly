"""Pydantic schemas for tags."""
import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TagBase(BaseModel):
    """Base tag schema."""

    name: str = Field(..., min_length=1, max_length=30)


class TagCreate(TagBase):
    """Schema for creating a tag."""

    @field_validator("name")
    @classmethod
    def validate_name(cls, v):
        if not v.strip():
            raise ValueError("Tag name cannot be empty")
        if len(v) > 30:
            raise ValueError("Tag name cannot exceed 30 characters")
        return v


class TagUpdate(TagBase):
    """Schema for updating a tag."""

    pass


class TagResponse(BaseModel):
    """Schema for tag response."""

    id: uuid_pkg.UUID
    name: str
    display_name: str
    color: str
    is_predefined: bool
    usage_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TagListResponse(BaseModel):
    """Schema for list of tags."""

    tags: list[TagResponse]
    total: int


class URLTagUpdate(BaseModel):
    """Schema for updating URL tags."""

    tag_ids: list[uuid_pkg.UUID] = Field(..., description="List of tag IDs")


class BulkTagUpdate(BaseModel):
    """Schema for bulk tagging."""

    short_codes: list[str] = Field(..., min_length=1)
    tag_ids: list[uuid_pkg.UUID] = Field(..., min_length=1)


class CampaignTagUpdate(BaseModel):
    """Schema for updating campaign tags."""

    tag_ids: list[uuid_pkg.UUID]
