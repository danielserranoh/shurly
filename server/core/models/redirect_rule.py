"""RedirectRule model — Phase 3.10.2 dynamic redirect rules."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class RedirectRule(Base):
    """
    Per-URL conditional redirect.

    Rules are evaluated in priority order at request time; the first whose
    `conditions` block matches takes precedence over the URL's `original_url`.
    Stored conditions are an opaque list-of-dicts (`{type, op?, value}`) so we
    can extend the matcher post-launch without a model migration.
    """

    __tablename__ = "redirect_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    url_id = Column(UUID(as_uuid=True), ForeignKey("urls.id"), nullable=False, index=True)

    # Lower priority value = evaluated first (stable, intuitive ordering).
    priority = Column(Integer, nullable=False, default=0, index=True)

    # List of condition dicts; AND across the list. See server/utils/redirect_rules.py.
    conditions = Column(JSON, nullable=False)

    target_url = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    url = relationship("URL", back_populates="redirect_rules")

    def __repr__(self) -> str:
        return f"<RedirectRule(url_id={self.url_id}, priority={self.priority})>"
