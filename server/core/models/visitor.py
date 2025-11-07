import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class Visitor(Base):
    """Visitor model for tracking URL visits."""

    __tablename__ = "visits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url_id = Column(UUID(as_uuid=True), ForeignKey("urls.id"), nullable=False, index=True)
    short_code = Column(String(20), nullable=False, index=True)  # Denormalized for performance

    # Visit metadata
    ip = Column(String(50), nullable=False)
    country = Column(String(100), nullable=True)  # e.g., "United States"
    user_agent = Column(Text, nullable=True)
    referer = Column(Text, nullable=True)

    visited_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    url = relationship("URL", back_populates="visits")

    def __repr__(self):
        return (
            f"<Visitor(short_code={self.short_code}, ip={self.ip}, visited_at={self.visited_at})>"
        )
