"""Tag model for organizing URLs and campaigns."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, CheckConstraint, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class Tag(Base):
    """Tag model for categorizing URLs and campaigns."""

    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(30), unique=True, nullable=False)  # lowercase
    display_name = Column(String(30), nullable=False)  # original case
    color = Column(String(20), nullable=False)  # e.g., "blue-500", "#3B82F6"
    is_predefined = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships (will be added after association tables are created)
    urls = relationship("URL", secondary="url_tags", back_populates="tags")
    campaigns = relationship("Campaign", secondary="campaign_tags", back_populates="tags")

    __table_args__ = (
        CheckConstraint("name = LOWER(name)", name="name_lowercase_check"),
    )

    def __repr__(self):
        return f"<Tag {self.display_name} ({self.name})>"


# URL-Tags association table (many-to-many)
url_tags = Table(
    "url_tags",
    Base.metadata,
    Column("url_id", UUID(as_uuid=True), ForeignKey("urls.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)

# Campaign-Tags association table (many-to-many)
campaign_tags = Table(
    "campaign_tags",
    Base.metadata,
    Column("campaign_id", UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime, default=datetime.utcnow, nullable=False),
)
