"""
Phase 3.13.2 — how people prove who they are.

- `UserIdentity`: an account at an identity provider (Google), recognised by the
  provider's subject (`sub`), which survives an email rename.
- `GoogleAuthState`: a Google sign-in in progress, i.e. the `state` sent to Google
  (hashed) and the PKCE verifier. Single use, 10 minutes.
- `LoginCode`: the one-time code the callback hands to the frontend, which trades
  it for a JWT. Stored hashed, single use, 60 seconds.

The rules live in `server/utils/google_sign_in.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String(32), nullable=False)
    subject = Column(String(255), nullable=False)
    # The address the provider gave at the last sign-in; `users.email` stays as it was.
    email = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="identities")

    def __repr__(self):
        return f"<UserIdentity(provider={self.provider}, user_id={self.user_id})>"


class GoogleAuthState(Base):
    __tablename__ = "google_auth_states"

    state_hash = Column(String(64), primary_key=True)
    code_verifier = Column(String(128), nullable=False)
    expires_at = Column(DateTime, nullable=False)


class LoginCode(Base):
    __tablename__ = "login_codes"

    code_hash = Column(String(64), primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
