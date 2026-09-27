"""Pydantic schemas for the organization and its members (Phase 3.14.2)."""

import uuid as uuid_pkg
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from server.core.models import OrgRole


class OrganizationResponse(BaseModel):
    """The caller's organization, and their role in it."""

    id: uuid_pkg.UUID
    name: str
    google_domain: str | None
    role: OrgRole


class MemberResponse(BaseModel):
    user_id: uuid_pkg.UUID
    email: str
    role: OrgRole
    joined_at: datetime


class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: OrgRole


class OwnershipTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: uuid_pkg.UUID
