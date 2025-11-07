import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

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

    # Campaign-related fields
    campaign_id = Column(UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True)
    user_data = Column(JSONB, nullable=True)  # Store arbitrary key-value pairs for campaign URLs

    # Audit fields
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    creator = relationship("User", back_populates="urls")
    campaign = relationship("Campaign", back_populates="urls")
    visits = relationship("Visitor", back_populates="url", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<URL(short_code={self.short_code}, type={self.url_type})>"
