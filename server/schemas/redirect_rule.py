"""Schemas for Phase 3.10.2 dynamic redirect rules."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from server.utils.url import is_valid_url


class RedirectRuleCreate(BaseModel):
    priority: int = Field(0, description="Lower value = evaluated first")
    conditions: list[dict[str, Any]] = Field(
        ..., description="List of {type, value, ...} dicts ANDed together"
    )
    target_url: str = Field(..., description="Destination when this rule matches")

    @field_validator("target_url")
    @classmethod
    def _validate_target(cls, v: str) -> str:
        if not is_valid_url(v):
            raise ValueError("Invalid target_url. Must be a valid http or https URL.")
        return v


class RedirectRuleUpdate(BaseModel):
    priority: int | None = None
    conditions: list[dict[str, Any]] | None = None
    target_url: str | None = None

    @field_validator("target_url")
    @classmethod
    def _validate_target(cls, v: str | None) -> str | None:
        if v and not is_valid_url(v):
            raise ValueError("Invalid target_url. Must be a valid http or https URL.")
        return v


class RedirectRuleResponse(BaseModel):
    id: UUID
    url_id: UUID
    priority: int
    conditions: list[dict[str, Any]]
    target_url: str
    created_at: datetime

    model_config = {"from_attributes": True}
