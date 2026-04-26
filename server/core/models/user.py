import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class ApiKeyScope(str, enum.Enum):
    """
    Phase 3.9.6 — API key scope enum (data model only at launch).

    FULL_ACCESS is the only behavioral value; the rest are reserved so that adding
    scope enforcement post-launch does not require a destructive enum migration.
    """

    FULL_ACCESS = "full_access"
    READ_ONLY = "read_only"
    CREATE_ONLY = "create_only"
    DOMAIN_SPECIFIC = "domain_specific"


class User(Base):
    """User model for authentication."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    api_key = Column(String(64), unique=True, nullable=True, index=True)
    api_key_scope = Column(
        Enum(ApiKeyScope), nullable=False, default=ApiKeyScope.FULL_ACCESS
    )
    api_key_constraints = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    urls = relationship("URL", back_populates="creator", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="creator", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"
