"""
Phase 3.14.2 — the organization and its members.

One organization at launch. Every account belongs to it with a role; the
rules for changing roles live in `server/utils/organization.py`.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import deferred, relationship

from server.core import Base
from server.utils.stored_image import version_of


class OrgRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    # Google Workspace domain whose accounts may sign in (3.13).
    google_domain = Column(String(255), nullable=True, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Phase 3.14.4 — the logo: a WebP within 512×512, its shape and transparency kept
    # (server/utils/logo.py). Deferred: reading the organization never loads the image, only
    # GET /organization/logo does.
    logo = deferred(Column(LargeBinary, nullable=True))
    logo_content_type = Column(String(32), nullable=True)
    # When it was uploaded, and so its version: in its URL (`?v=`) and its ETag.
    logo_updated_at = Column(DateTime, nullable=True)

    @property
    def logo_version(self) -> str | None:
        """Changes with each upload; None without a logo."""
        return version_of(self.logo_updated_at)

    def __repr__(self):
        return f"<Organization(id={self.id}, name={self.name})>"


class OrganizationMember(Base):
    __tablename__ = "organization_members"

    organization_id = Column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role = Column(Enum(OrgRole), nullable=False, default=OrgRole.MEMBER)
    joined_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")

    def __repr__(self):
        return f"<OrganizationMember(user_id={self.user_id}, role={self.role})>"
