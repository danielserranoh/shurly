"""
Phase 3.12 — the profile: names, country and time zone, one per user.

Its own table rather than columns on `users`, which `server/core/auth.py` loads on every
authenticated request; the profile is read by /auth/me and Settings only. The row is made
on the first save, so an account without one has an empty profile. The rules for each
field live in `server/utils/profile.py`.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    first_name = Column(String(100), nullable=True)
    last_name = Column(String(100), nullable=True)
    # ISO 3166-1 alpha-2 ("ES")
    country = Column(String(2), nullable=True)
    # An IANA name ("Atlantic/Canary"), never an offset: offsets change with DST.
    timezone = Column(String(64), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="profile")

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id})>"
