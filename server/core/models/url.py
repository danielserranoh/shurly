import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from server.core import Base


class URLType(str, enum.Enum):
    """Type of URL shortening."""

    STANDARD = "standard"
    CUSTOM = "custom"
    CAMPAIGN = "campaign"


class URL(Base):
    """URL model for storing shortened URLs."""

    __tablename__ = "urls"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    short_code = Column(String(20), unique=True, nullable=False, index=True)
    original_url = Column(Text, nullable=False)
    url_type = Column(Enum(URLType), nullable=False, default=URLType.STANDARD)
    title = Column(String(255), nullable=True)  # User-friendly title for the URL

    # Campaign-related fields
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    user_data = Column(JSON, nullable=True)  # Store arbitrary key-value pairs for campaign URLs

    # URL behavior settings
    forward_parameters = Column(Boolean, default=True, nullable=False)  # Forward query params to destination

    # Open Graph metadata for social media previews
    og_title = Column(String(255), nullable=True)
    og_description = Column(Text, nullable=True)
    og_image_url = Column(Text, nullable=True)
    og_fetched_at = Column(DateTime(timezone=True), nullable=True)

    # Analytics tracking
    last_click_at = Column(DateTime(timezone=True), nullable=True)

    # Phase 3.9.2 — Validity window and visit cap (Shlink-inspired)
    # All NULL by default → no constraint. valid_since/valid_until enforce a date window;
    # max_visits enforces a hard cap on real (non-crawler) visits before serving 410 Gone.
    valid_since = Column(DateTime(timezone=True), nullable=True)
    valid_until = Column(DateTime(timezone=True), nullable=True)
    max_visits = Column(Integer, nullable=True)

    # Phase 3.9.4 — Default-deny crawlability. Short URLs are not crawler-indexable
    # by default; flip to True per-URL to allow inclusion in /robots.txt.
    crawlable = Column(Boolean, default=False, nullable=False)

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=func.now(), nullable=False)

    # Relationships
    creator = relationship("User", back_populates="urls")
    campaign = relationship("Campaign", back_populates="urls")
    visits = relationship("Visitor", back_populates="url", cascade="all, delete-orphan")
    tags = relationship("Tag", secondary="url_tags", back_populates="urls")

    def __repr__(self):
        return f"<URL(short_code={self.short_code}, type={self.url_type})>"
