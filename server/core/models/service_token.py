"""
Phase 10.1 — a service account's token (`_pm/spec_service_accounts.md`).

`shsa_<prefix>_<secret>`: the `shsa_` start lets secret scanners recognize a leaked one, the
prefix tells tokens apart in the UI, and the secret is 32 random bytes. Shown once, when it's
made; kept only as its SHA-256 (`hash_api_key`, as API keys are).

One token per account is active (neither replaced nor revoked), plus at most one in its 24-hour
overlap after a renewal: it still authenticates until `replaced_at + RENEWAL_OVERLAP`. Revoking
ends a token at once. The rules live in `server/utils/service_accounts.py`; authenticating with
one, in `server/core/auth.py`.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from server.core import Base

SERVICE_TOKEN_START = "shsa_"
# How long a renewed token keeps working, so the service can switch without failing requests.
RENEWAL_OVERLAP = timedelta(hours=24)
# `last_used_at` is written at most this often: a busy integration doesn't write on every request.
LAST_USED_RESOLUTION = timedelta(minutes=1)


class ServiceToken(Base):
    __tablename__ = "service_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    service_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The characters between `shsa_` and the second `_`: shown again, to tell tokens apart.
    prefix = Column(String(16), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    # All naive UTC, as the other columns. No IP is kept, ever.
    expires_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)
    created_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    replaced_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    service_account = relationship("User", foreign_keys=[service_account_id])

    @property
    def shown_prefix(self) -> str:
        """How the token starts, as the UI shows it: `shsa_<prefix>`."""
        return f"{SERVICE_TOKEN_START}{self.prefix}"

    @property
    def overlap_ends_at(self) -> datetime | None:
        """When a renewed token stops working; None while it's the active one."""
        return self.replaced_at + RENEWAL_OVERLAP if self.replaced_at is not None else None

    def is_valid(self, now: datetime) -> bool:
        """Authenticates at `now` (naive UTC): not revoked, not expired, not past its overlap."""
        if self.revoked_at is not None:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        ends = self.overlap_ends_at
        return ends is None or now < ends

    def __repr__(self) -> str:
        return f"<ServiceToken(id={self.id}, prefix={self.prefix})>"
