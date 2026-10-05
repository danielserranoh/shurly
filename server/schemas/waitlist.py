"""Phase 9.1 — the waitlist's request and responses (server/app/waitlist.py)."""

from __future__ import annotations

import uuid
from typing import Literal

from email_validator import EmailNotValidError, validate_email
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from server.core.models.waitlist import (
    COMPANY_LENGTH,
    EMAIL_LENGTH,
    NAME_LENGTH,
    ROLE_LENGTH,
    SOURCE_LENGTH,
    USE_CASE_LENGTH,
)
from server.schemas.datetimes import UtcDateTime

Kind = Literal["individual", "company"]
CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1000+"]


class WaitlistJoin(BaseModel):
    """What the waitlist form sends. Every value is trimmed; an empty optional one is none."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(max_length=EMAIL_LENGTH, description="Stored in lowercase")
    name: str = Field(min_length=1, max_length=NAME_LENGTH)
    kind: Kind = Field(description="Signing up as an individual, or for a company")
    company: str | None = Field(
        None,
        max_length=COMPANY_LENGTH,
        validate_default=True,
        description="Required for a company; dropped for an individual",
    )
    company_size: CompanySize | None = Field(
        None, validate_default=True, description="A company's, if given"
    )
    role: str | None = Field(None, max_length=ROLE_LENGTH)
    use_case: str | None = Field(
        None, max_length=USE_CASE_LENGTH, description="What they'd use Shurly for"
    )
    source: str | None = Field(None, max_length=SOURCE_LENGTH, description="How they heard of it")
    consent: bool = Field(description="Agrees to be contacted about Shurly: must be true")
    # The honeypot: a field people never see. Filled, the sign-up is a bot's and isn't stored.
    website: str | None = Field(None, max_length=500, description="Leave empty")

    @field_validator("email")
    @classmethod
    def an_email(cls, value: str) -> str:
        try:
            checked = validate_email(value, check_deliverability=False)
        except EmailNotValidError:
            raise ValueError("Enter an email address, like you@company.com.") from None
        return checked.normalized.lower()

    @field_validator("company", "role", "use_case", "source", "website", mode="before")
    @classmethod
    def blank_is_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("company_size", mode="before")
    @classmethod
    def blank_size_is_none(cls, value):
        return None if value == "" else value

    @field_validator("consent")
    @classmethod
    def consented(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Agree to be contacted about Shurly to join the waitlist.")
        return value

    @field_validator("company", mode="after")
    @classmethod
    def a_company_has_a_name(cls, value: str | None, info: ValidationInfo) -> str | None:
        kind = info.data.get("kind")
        if kind == "individual":
            return None
        if kind == "company" and not value:
            raise ValueError("Enter the company’s name.")
        return value

    @field_validator("company_size", mode="after")
    @classmethod
    def only_a_companys(cls, value: str | None, info: ValidationInfo) -> str | None:
        return None if info.data.get("kind") == "individual" else value


class WaitlistJoined(BaseModel):
    """The same answer for every sign-up: it never says whether the email was already listed."""

    status: Literal["on_the_list"] = "on_the_list"


class WaitlistEntryResponse(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    kind: Kind
    company: str | None
    company_size: CompanySize | None
    role: str | None
    use_case: str | None
    source: str | None
    consent_at: UtcDateTime
    created_at: UtcDateTime
    updated_at: UtcDateTime | None

    model_config = ConfigDict(from_attributes=True)


class WaitlistCounts(BaseModel):
    """Everyone on the list, by kind, and the companies by size (`not_given`: no size)."""

    total: int
    individual: int
    company: int
    by_company_size: dict[str, int]


class WaitlistListResponse(BaseModel):
    entries: list[WaitlistEntryResponse] = Field(description="Newest first")
    total: int
    counts: WaitlistCounts
