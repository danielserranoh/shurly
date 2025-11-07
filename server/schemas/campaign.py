"""Schemas for campaign management."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.utils.url import is_valid_url


class CampaignCreate(BaseModel):
    """Schema for creating a campaign with CSV data."""

    name: str = Field(..., description="Name of the campaign", min_length=1, max_length=255)
    original_url: str = Field(..., description="Base URL for all campaign URLs")
    csv_data: str = Field(..., description="CSV data with header row")

    @field_validator("original_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid URL format. Must be a valid http or https URL.")
        return v

    @field_validator("csv_data")
    @classmethod
    def validate_csv_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("CSV data cannot be empty")
        return v


class CampaignURLResponse(BaseModel):
    """Schema for a single URL in a campaign."""

    id: UUID
    short_code: str
    short_url: str | None = None
    user_data: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CampaignResponse(BaseModel):
    """Schema for campaign response."""

    id: UUID
    name: str
    original_url: str
    csv_columns: list[str]
    url_count: int
    created_at: datetime
    urls: list[CampaignURLResponse] | None = None  # Only included in detail view

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    """Schema for list of campaigns."""

    campaigns: list[CampaignResponse]
    total: int


class CampaignExportRow(BaseModel):
    """Schema for exporting campaign URLs as CSV."""

    short_code: str
    short_url: str
    original_url: str
    user_data: dict | None = None
