import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class Campaign(Base):
    """Campaign model for bulk URL creation."""

    __tablename__ = "campaigns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    original_url = Column(Text, nullable=False)
    csv_columns = Column(
        JSON, nullable=False
    )  # e.g., ['firstName', 'lastName', 'company'] - stored as JSON for SQLite compatibility

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Phase 3.14.3 — the organization the campaign belongs to. NULL = personal.
    organization_id = Column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )

    # Relationships
    creator = relationship("User", back_populates="campaigns")
    urls = relationship("URL", back_populates="campaign", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary="campaign_tags", back_populates="campaigns")

    @property
    def visibility(self) -> str:
        return "personal" if self.organization_id is None else "organization"

    @property
    def created_by_email(self) -> str | None:
        """Lists eager-load `creator`, or this costs a query per campaign."""
        return self.creator.email if self.creator else None

    # Phase 3.12 — the creator's name, from their profile. Lists eager-load `creator` and
    # its `profile`, or these cost queries per campaign.
    @property
    def created_by_first_name(self) -> str | None:
        profile = self.creator.profile if self.creator else None
        return profile.first_name if profile else None

    @property
    def created_by_last_name(self) -> str | None:
        profile = self.creator.profile if self.creator else None
        return profile.last_name if profile else None

    def __repr__(self):
        return f"<Campaign(id={self.id}, name={self.name})>"
