"""Schemas for service accounts and their tokens (Phase 10.1)."""

import uuid as uuid_pkg
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from server.schemas.datetimes import UtcDateTime

ServiceRole = Literal["member", "admin"]


class ResponsiblePerson(BaseModel):
    """The person responsible for a service account."""

    user_id: uuid_pkg.UUID
    email: str
    first_name: str | None = None
    last_name: str | None = None


class ServiceTokenInfo(BaseModel):
    """A token, as Shurly shows it again: how it starts, never the token or its hash."""

    id: uuid_pkg.UUID
    prefix: str = Field(description="How the token starts, `shsa_<prefix>`: to tell tokens apart")
    created_at: UtcDateTime
    expires_at: UtcDateTime | None = Field(None, description="Null: it doesn't expire")
    last_used_at: UtcDateTime | None = Field(
        None, description="When it last authenticated, to the minute; null: never"
    )
    valid_until: UtcDateTime | None = Field(
        None,
        description="A renewed token's end of overlap: it works until then. Null for the active one",
    )


class ServiceAccountResponse(BaseModel):
    id: uuid_pkg.UUID
    display_name: str
    description: str | None = None
    role: ServiceRole
    responsible: ResponsiblePerson | None = None
    created_at: UtcDateTime
    token: ServiceTokenInfo | None = Field(None, description="The active token; null: none")
    previous_token: ServiceTokenInfo | None = Field(
        None, description="The token it replaced, still working in its 24-hour overlap"
    )


class ServiceAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(..., min_length=1, max_length=255, examples=["Propuestas Griddo"])
    description: str | None = Field(None, max_length=1000)
    responsible_user_id: uuid_pkg.UUID = Field(description="A person in the organization")
    role: ServiceRole = "member"


class ServiceAccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    responsible_user_id: uuid_pkg.UUID | None = None
    role: ServiceRole | None = None


class ServiceTokenCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expires_at: UtcDateTime | None = Field(
        None, description="When it stops working, in the future; null: it doesn't expire"
    )


class ServiceTokenIssued(ServiceTokenInfo):
    """A new token: the secret, this once. Shurly keeps only its hash."""

    token: str = Field(description="`shsa_<prefix>_<secret>`. Shown only now: keep it safe")
    renewed: bool = Field(description="It replaced a token, which keeps working for 24 hours")
    service_account: ServiceAccountResponse
