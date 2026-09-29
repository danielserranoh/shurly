import enum
import hashlib
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


# Phase 6.3 — how much of an API key is kept to tell it apart ("shurly_AbC12").
API_KEY_PREFIX_LENGTH = 12


def hash_api_key(key: str) -> str:
    """What's stored of an API key. SHA-256 is enough: keys are 256 random bits,
    so a slow hash buys nothing, and a fixed digest can be looked up by index."""
    return hashlib.sha256(key.encode()).hexdigest()


class User(Base):
    """User model for authentication."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    # Phase 3.13.3 — NULL: no password (an account made by signing in with Google).
    password_hash = Column(String(255), nullable=True)
    # Phase 6.3 — API keys are kept as a hash and a prefix, never as themselves: a key
    # is shown once, when it's made (set_api_key). The plaintext column, users.api_key,
    # is empty since migration 0007 and isn't mapped: the ORM names every mapped column
    # in its SELECTs and INSERTs, and 0011 drops it in the next release while this one
    # still serves.
    api_key_hash = Column(String(64), unique=True, nullable=True, index=True)
    api_key_prefix = Column(String(API_KEY_PREFIX_LENGTH), nullable=True)
    api_key_scope = Column(Enum(ApiKeyScope), nullable=False, default=ApiKeyScope.FULL_ACCESS)
    api_key_constraints = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    # Phase 3.13.3 — JWTs issued in an earlier second are refused (server/core/auth.py).
    sessions_valid_from = Column(DateTime, nullable=True)

    # Relationships
    urls = relationship("URL", back_populates="creator", cascade="all, delete-orphan")
    campaigns = relationship("Campaign", back_populates="creator", cascade="all, delete-orphan")
    identities = relationship("UserIdentity", back_populates="user")
    # Phase 3.12 — loaded when read, never with the user: auth loads users on every request.
    profile = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def has_password(self) -> bool:
        return self.password_hash is not None

    @property
    def has_api_key(self) -> bool:
        return self.api_key_hash is not None

    def set_api_key(self, key: str) -> None:
        """Keep `key` as its hash and prefix; the key itself is the caller's to show once."""
        self.api_key_hash = hash_api_key(key)
        self.api_key_prefix = key[:API_KEY_PREFIX_LENGTH]

    def clear_api_key(self) -> None:
        self.api_key_hash = None
        self.api_key_prefix = None

    @property
    def has_google(self) -> bool:
        return any(identity.provider == "google" for identity in self.identities)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"
