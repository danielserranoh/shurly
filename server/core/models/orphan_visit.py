"""OrphanVisit model — Phase 3.10.4."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Enum, String, Text
from sqlalchemy.dialects.postgresql import UUID

from server.core import Base


class OrphanVisitType(str, enum.Enum):
    """Why we're recording this orphan visit."""

    BASE_URL = "base_url"
    INVALID_SHORT_URL = "invalid_short_url"
    REGULAR_404 = "regular_404"


class OrphanVisit(Base):
    """
    A request that *would have* hit a short URL but didn't resolve to one.

    Useful for catching typo'd codes leaked into print/QR campaigns and for
    detecting scanning behavior. Logged by the catch-all handler before it
    returns 404.
    """

    __tablename__ = "orphan_visits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(Enum(OrphanVisitType), nullable=False, index=True)
    attempted_path = Column(String(2048), nullable=False)
    ip = Column(String(50), nullable=True)
    user_agent = Column(Text, nullable=True)
    referer = Column(Text, nullable=True)
    created_at = Column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<OrphanVisit(type={self.type}, path={self.attempted_path})>"
