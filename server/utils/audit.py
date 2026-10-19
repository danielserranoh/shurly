"""
Phase 10.2 — writing the audit of what service accounts do (`AuditEvent`,
server/core/models/audit_event.py; `_pm/spec_service_accounts.md`, v2).

- **`record`** adds one row when a service account acts (`acting.service` is set) and does
  nothing for a person. It adds the row to the caller's session without flushing or
  committing: the row commits with the change, or rolls back with it.
- **`record_account_event`** is for the events on an account or its tokens, which a person
  (the owner) makes: `actor_id` is theirs, and there is no token or person acted for.
- **`acting_on_any_change`** is who a change acts as, on the routes that took no
  `X-Shurly-On-Behalf-Of` before 10.2 (tags, redirect rules, campaign delete and tags, bulk tags).

The action is `<target_type>.<verb>`: `url.created`, `campaign.deleted`, `redirect_rule.updated`.
`target_id` is the target's id, never its short code or name: a slug can be someone's name.
`detail` holds ids and field names only, never the values (server/utils/event_log.py:9-10):
`{"fields": ["title", "tags"]}`, `{"tag_ids": [...]}`, `{"url_id": ...}`.

**Its organization** is the service account's: the organization it is a member of, whose owners
and admins read the audit (`ensure_reader`). Whatever a service account touches is that
organization's: its links and campaigns always are (`Viewer.organization_for`), it changes only
links it sees, and tags have no organization. A service account without a membership has been
removed, and its token no longer authenticates; were one to act anyway, nothing is written and
`audit.skipped` is logged, so the change itself still goes through.
"""

from __future__ import annotations

import re
import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from server.core.models import AuditEvent, User
from server.utils.event_log import log_event
from server.utils.organization import get_membership
from server.utils.service_accounts import Acting, acting_on_change

_ACTION = re.compile(r"^([a-z_]+)\.([a-z_]+)$")


def _target_type(action: str) -> str:
    match = _ACTION.match(action)
    if match is None:
        raise ValueError(f"An audit action is `<target_type>.<verb>`, not {action!r}")
    return match.group(1)


def _as_text(value) -> str | None:
    return None if value is None else str(value)


def acting_on_any_change(db: Session, request: Request, user: User) -> Acting:
    """
    Who a change acts as, on a route that ignored `X-Shurly-On-Behalf-Of` before 10.2.

    A service account: `acting_on_change` (the header names the person acted for, and grants
    nothing). A person: themselves, the header ignored as before, so these routes don't start
    answering 403 to a person who sends it.
    """
    if user.is_service:
        return acting_on_change(db, request, user)
    return Acting(creator=user)


def record(
    db: Session,
    *,
    acting: Acting,
    action: str,
    target_id,
    detail: dict | None = None,
) -> AuditEvent | None:
    """
    Add an audit row for what a service account did, in the caller's transaction (no flush, no
    commit). A person's change writes none: returns None.

    `action` is `<target_type>.<verb>`; `target_id` the target's id; `detail` ids and field
    names only, never values.
    """
    target_type = _target_type(action)
    if acting.service is None:
        return None
    membership = get_membership(db, acting.service)
    if membership is None:
        log_event("audit.skipped", action=action, service_account_id=str(acting.service.id))
        return None
    row = AuditEvent(
        organization_id=membership.organization_id,
        service_account_id=acting.service.id,
        token_id=acting.token_id,
        on_behalf_of_id=acting.on_behalf_of.id if acting.on_behalf_of else None,
        action=action,
        target_type=target_type,
        target_id=_as_text(target_id),
        detail=detail or None,
    )
    db.add(row)
    return row


def record_account_event(
    db: Session,
    *,
    actor: User,
    account_id: uuid.UUID,
    organization_id: uuid.UUID,
    action: str,
    target_id=None,
    token_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> AuditEvent:
    """
    Add an audit row for an event a person made on a service account or its tokens
    (`service_account.created`, `service_token.renewed`, …), in the caller's transaction.
    `actor_id` is that person; there is no person acted for. `target_id` defaults to the
    account (`service_account.*`) or the token (`service_token.*`).
    """
    target_type = _target_type(action)
    if target_id is None:
        target_id = token_id if target_type == "service_token" else account_id
    row = AuditEvent(
        organization_id=organization_id,
        service_account_id=account_id,
        token_id=token_id,
        actor_id=actor.id,
        on_behalf_of_id=None,
        action=action,
        target_type=target_type,
        target_id=_as_text(target_id),
        detail=detail or None,
    )
    db.add(row)
    return row
