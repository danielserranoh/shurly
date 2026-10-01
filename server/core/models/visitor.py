import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class Visitor(Base):
    """Visitor model for tracking URL visits."""

    __tablename__ = "visits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url_id = Column(UUID(as_uuid=True), ForeignKey("urls.id"), nullable=False, index=True)
    # Denormalized, for orphan checks and debugging. Never a link's key in queries: the same
    # code can name links on two domains, so a link's visits are those with its url_id.
    # As long as a link's (MAX_SHORT_CODE_LENGTH, 64 since 0013).
    short_code = Column(String(64), nullable=False, index=True)

    # Visit metadata
    ip = Column(String(50), nullable=False)
    country = Column(String(100), nullable=True)  # ISO 3166-1 alpha-2 (Phase 8.4), e.g. "US"
    # Phase 8.4 — its English name, from GeoLite2 City, e.g. "Zaragoza". Never shown per visit.
    city = Column(String(128), nullable=True)
    user_agent = Column(Text, nullable=True)
    referer = Column(Text, nullable=True)

    # Phase 3.9.3 — Bot classification at log time. Used to default-filter analytics
    # so headless crawlers, link previewers and scanners don't pollute click counts.
    is_bot = Column(Boolean, default=False, nullable=False, index=True)

    # Phase 3.10.3 — Email tracking pixel hits. Stored on the same table so the
    # opens timeline naturally lines up with click analytics, but is_pixel=True
    # rows are excluded from "clicks" counts by default.
    is_pixel = Column(Boolean, default=False, nullable=False, index=True)

    visited_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationships
    url = relationship("URL", back_populates="visits")

    def __repr__(self):
        return (
            f"<Visitor(short_code={self.short_code}, ip={self.ip}, visited_at={self.visited_at})>"
        )
