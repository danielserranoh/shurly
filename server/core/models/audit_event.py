"""
Phase 10.2 — the audit of what service accounts do (`_pm/spec_service_accounts.md`, v2).

One row per action a service account takes (a link made, a campaign deleted, a tag changed, and
on whose behalf) and per event on an account or its tokens (made, renewed, revoked, removed).
Kept 2 years, then the housekeeping job deletes it; the organization's owners and admins read it.

Ids only, never values, as the event log (`server/utils/event_log.py`): `detail` holds ids and
the names of the fields changed, never what they held. People's emails are resolved when the
table is read, and someone deleted shows as such.

The ids are plain columns, without foreign keys, so the audit outlives what it names: a
CASCADE would delete the rows with the account, token or person, a SET NULL would erase who
acted, and a RESTRICT would keep a person from being deleted for 2 years.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID

from server.core import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        # The organization's audit, newest first, paged by time.
        Index("ix_audit_events_organization_id_at", "organization_id", "at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Naive UTC, as the other columns.
    at = Column(DateTime, default=datetime.utcnow, nullable=False)
    organization_id = Column(UUID(as_uuid=True), nullable=False)
    # The service account that acted, or whose account or token the event is about.
    service_account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    # The token it used; NULL for an event an owner made (creating the account, say).
    token_id = Column(UUID(as_uuid=True), nullable=True)
    # The person who made an account or token event; NULL when the service account acted.
    actor_id = Column(UUID(as_uuid=True), nullable=True)
    # The person named in `X-Shurly-On-Behalf-Of`, when there was one.
    on_behalf_of_id = Column(UUID(as_uuid=True), nullable=True)
    # What happened, as `<target>.<verb>`: `url.created`, `service_token.renewed`.
    action = Column(String(64), nullable=False)
    target_type = Column(String(32), nullable=False)
    # The id of what it acted on (never a short code or a name).
    target_id = Column(String(64), nullable=True)
    # Ids and field names only, never the values.
    detail = Column(JSON, nullable=True)

    def __repr__(self) -> str:
        return f"<AuditEvent(id={self.id}, action={self.action})>"
