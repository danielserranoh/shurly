"""Domain model — Phase 3.10.1 multi-domain foundation."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from server.core import Base


class Domain(Base):
    """
    A short-link host (e.g. `shurl.griddo.io`).

    At launch we run with a single default domain; the model exists so the URL
    table can carry `domain_id` and the redirect resolver can match by Host
    header without a destructive migration when we open up multi-tenancy.
    """

    __tablename__ = "domains"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = Column(String(255), unique=True, nullable=False, index=True)
    is_default = Column(Boolean, default=False, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Domain(hostname={self.hostname}, is_default={self.is_default})>"
