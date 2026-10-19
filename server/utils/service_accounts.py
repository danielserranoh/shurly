"""
Phase 10.1 — service accounts: another system that acts for the organization
(`_pm/spec_service_accounts.md`).

A service account is a `users` row with `kind = 'service'`, a display name, a description and a
person responsible, and a membership of the organization as `member` or `admin`. It never signs
in; it authenticates with its one token (`ServiceToken`, server/core/auth.py).

- **Managing them** is for the organization's owner, signed in; its admins read the list.
  Members, API keys and service tokens can't (`ensure_reader`, `ensure_owner`).
- **Its token** is made, renewed and revoked here. Renewing keeps the old one working for
  24 hours (`RENEWAL_OVERLAP`); revoking ends tokens at once. The secret is returned once and
  only its hash is kept.
- **Acting on behalf of a person** (`X-Shurly-On-Behalf-Of: <email>`, `acting_for`): only a
  service token may send it, and it only decides whom a new link is attributed to: the
  person becomes its creator, and the link keeps which service account and token made it. It
  grants nothing: the service acts with its own role.
- **Removing one** revokes its tokens, takes it out of the organization and closes it. Its
  links stay, with the account named.

Events (server/utils/event_log.py): `service_account.created`, `.updated`, `.removed`, and
`service_token.created`, `.renewed`, `.revoked`. Ids only: never a secret, a hash or an email.
Phase 10.2: each also writes an audit row (`audit.record_account_event`), the owner as its
actor, in the same transaction; `audit_page` reads them back for the organization.

Phase 10.2 also gives each token its `scopes` and `allowed_ip_ranges` (a renewal inherits them
unless the request sets them), and its `warnings` (`token_warnings`): it expires within 14
days, or nothing has used it for 90. `attention_count` counts the tokens with one.

These functions flush but don't commit: the caller owns the transaction.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from server.core.models import AuditEvent, OrganizationMember, OrgRole, ServiceToken, User
from server.core.models.service_token import SERVICE_SCOPES, SERVICE_TOKEN_START, every_scope
from server.core.models.user import PERSON, SERVICE, SERVICE_EMAIL_DOMAIN, hash_api_key
from server.utils.errors import (
    ON_BEHALF_OF_NOT_ALLOWED,
    ON_BEHALF_OF_UNKNOWN,
    CodedHTTPException,
)
from server.utils.event_log import log_event
from server.utils.organization import get_membership

ON_BEHALF_HEADER = "X-Shurly-On-Behalf-Of"
SERVICE_ROLES = (OrgRole.MEMBER, OrgRole.ADMIN)
# The prefix: 8 hex characters, so it never holds the `_` that ends it.
PREFIX_BYTES = 4
# The secret: 32 random bytes, URL-safe base64 (43 characters).
SECRET_BYTES = 32
# Phase 10.2 — when a token needs attention: it expires within this…
EXPIRES_SOON = timedelta(days=14)
# …or nothing has used it for this long (`last_used_at`, or `created_at` if never used).
UNUSED_FOR = timedelta(days=90)
EXPIRES_SOON_WARNING = "expires_soon"
UNUSED_WARNING = "unused"
# A renewal keeps the replaced token's settings unless the request sets them.
INHERIT = object()


class ServiceAccountError(Exception):
    """A change the rules don't allow."""


class NotAllowed(ServiceAccountError):
    """The actor's role, or what they are, doesn't allow it (403)."""


class NotFound(ServiceAccountError):
    """No such service account in the actor's organization (404)."""


class Invalid(ServiceAccountError):
    """A value the account can't take (422)."""


# ---------------------------------------------------------------- Who manages them


def _membership_of_person(db: Session, actor: User) -> OrganizationMember | None:
    if actor.is_service:
        raise NotAllowed("A service account can't manage service accounts.")
    return get_membership(db, actor)


def ensure_reader(db: Session, actor: User) -> OrganizationMember:
    """The actor's membership, if they may see the service accounts: an owner or an admin."""
    mine = _membership_of_person(db, actor)
    if mine is None or mine.role not in (OrgRole.OWNER, OrgRole.ADMIN):
        raise NotAllowed("Only the organization’s owners and admins see its service accounts.")
    return mine


def ensure_owner(db: Session, actor: User) -> OrganizationMember:
    """The actor's membership, if they may change the service accounts: an owner."""
    mine = _membership_of_person(db, actor)
    if mine is None or mine.role != OrgRole.OWNER:
        raise NotAllowed("Only the organization’s owners manage its service accounts.")
    return mine


def accounts_of(db: Session, organization_id: uuid.UUID) -> list[tuple[User, OrgRole]]:
    """The organization's service accounts and their roles, by name."""
    rows = (
        db.query(User, OrganizationMember.role)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(
            OrganizationMember.organization_id == organization_id,
            User.kind == SERVICE,
            User.is_active.is_(True),
        )
        .all()
    )
    return sorted(rows, key=lambda row: ((row[0].display_name or "").lower(), str(row[0].id)))


def get_account(
    db: Session, mine: OrganizationMember, account_id: uuid.UUID
) -> tuple[User, OrganizationMember]:
    """A service account of the actor's organization, with its membership; NotFound otherwise."""
    row = (
        db.query(User, OrganizationMember)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(
            User.id == account_id,
            User.kind == SERVICE,
            User.is_active.is_(True),
            OrganizationMember.organization_id == mine.organization_id,
        )
        .first()
    )
    if row is None:
        raise NotFound("Service account not found")
    return row[0], row[1]


def _responsible(db: Session, mine: OrganizationMember, user_id: uuid.UUID) -> User:
    """The person responsible: an active person of the organization."""
    person = (
        db.query(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(
            User.id == user_id,
            User.kind == PERSON,
            User.is_active.is_(True),
            OrganizationMember.organization_id == mine.organization_id,
        )
        .first()
    )
    if person is None:
        raise Invalid("The person responsible must be someone in the organization.")
    return person


def _clean_name(value: str | None) -> str:
    name = (value or "").strip()
    if not name:
        raise Invalid("Give the service account a name.")
    return name


def _role(value: OrgRole | str) -> OrgRole:
    try:
        role = OrgRole(value)
    except ValueError:
        role = None
    if role not in SERVICE_ROLES:
        raise Invalid("A service account is a member or an admin.")
    return role


def _placeholder_email(display_name: str) -> str:
    """`propuestas-griddo-1a2b3c4d@service.invalid`: unique, and never a Google account."""
    slug = re.sub(r"[^a-z0-9]+", "-", display_name.lower()).strip("-")[:40] or "service"
    return f"{slug}-{uuid.uuid4().hex[:8]}@{SERVICE_EMAIL_DOMAIN}"


# ---------------------------------------------------------------- The accounts


def create_account(
    db: Session,
    actor: User,
    *,
    display_name: str,
    description: str | None,
    responsible_user_id: uuid.UUID,
    role: OrgRole | str,
) -> tuple[User, OrganizationMember]:
    mine = ensure_owner(db, actor)
    name = _clean_name(display_name)
    responsible = _responsible(db, mine, responsible_user_id)
    account = User(
        email=_placeholder_email(name),
        password_hash=None,
        is_active=True,
        kind=SERVICE,
        display_name=name,
        description=(description or "").strip() or None,
        responsible_user_id=responsible.id,
    )
    db.add(account)
    db.flush()
    membership = OrganizationMember(
        organization_id=mine.organization_id, user_id=account.id, role=_role(role)
    )
    db.add(membership)
    db.flush()
    log_event(
        "service_account.created",
        actor_id=str(actor.id),
        service_account_id=str(account.id),
        role=membership.role.value,
    )
    _audit(db, actor, account, mine.organization_id, "service_account.created")
    return account, membership


def update_account(
    db: Session, actor: User, account_id: uuid.UUID, changes: dict
) -> tuple[User, OrganizationMember]:
    """Change the display name, description, person responsible or role: those sent."""
    mine = ensure_owner(db, actor)
    account, membership = get_account(db, mine, account_id)
    changed = []
    if "display_name" in changes:
        name = _clean_name(changes["display_name"])
        if name != account.display_name:
            account.display_name = name
            changed.append("display_name")
    if "description" in changes:
        description = (changes["description"] or "").strip() or None
        if description != account.description:
            account.description = description
            changed.append("description")
    if "responsible_user_id" in changes:
        if changes["responsible_user_id"] is None:
            raise Invalid("A service account needs a person responsible.")
        responsible = _responsible(db, mine, changes["responsible_user_id"])
        if responsible.id != account.responsible_user_id:
            account.responsible_user_id = responsible.id
            changed.append("responsible_user_id")
    if "role" in changes:
        if changes["role"] is None:
            raise Invalid("A service account is a member or an admin.")
        role = _role(changes["role"])
        if role != membership.role:
            membership.role = role
            changed.append("role")
    db.flush()
    if changed:
        log_event(
            "service_account.updated",
            actor_id=str(actor.id),
            service_account_id=str(account.id),
            fields=changed,
            role=membership.role.value,
        )
        _audit(
            db,
            actor,
            account,
            mine.organization_id,
            "service_account.updated",
            detail={"fields": changed},
        )
    return account, membership


def remove_account(db: Session, actor: User, account_id: uuid.UUID) -> None:
    """Revoke its tokens, take it out of the organization and close it. Its links stay."""
    mine = ensure_owner(db, actor)
    account, membership = get_account(db, mine, account_id)
    revoked = _revoke(db, actor, account, mine.organization_id, old_only=False)
    account.is_active = False
    db.delete(membership)
    db.flush()
    log_event(
        "service_account.removed",
        actor_id=str(actor.id),
        service_account_id=str(account.id),
        tokens_revoked=len(revoked),
    )
    _audit(db, actor, account, mine.organization_id, "service_account.removed")


def _audit(
    db: Session,
    actor: User,
    account: User,
    organization_id: uuid.UUID,
    action: str,
    *,
    token_id: uuid.UUID | None = None,
    detail: dict | None = None,
) -> None:
    """The event's audit row, by the owner who made it, in the caller's transaction."""
    from server.utils import audit  # it imports this module

    audit.record_account_event(
        db,
        actor=actor,
        account_id=account.id,
        organization_id=organization_id,
        action=action,
        token_id=token_id,
        detail=detail,
    )


# ---------------------------------------------------------------- Its token


def new_service_token() -> tuple[str, str]:
    """A new token and its prefix: `shsa_<prefix>_<secret>`. Shown once, kept as a hash."""
    prefix = secrets.token_hex(PREFIX_BYTES)
    return f"{SERVICE_TOKEN_START}{prefix}_{secrets.token_urlsafe(SECRET_BYTES)}", prefix


def live_tokens(db: Session, account: User, now: datetime | None = None) -> list[ServiceToken]:
    """The tokens that still authenticate: the active one, and one in its overlap. Newest first."""
    now = now or datetime.utcnow()
    rows = (
        db.query(ServiceToken)
        .filter(ServiceToken.service_account_id == account.id, ServiceToken.revoked_at.is_(None))
        .order_by(ServiceToken.created_at.desc())
        .all()
    )
    return [row for row in rows if row.is_valid(now)]


def _clean_scopes(scopes) -> list[str]:
    """Each known scope once, in `SERVICE_SCOPES`' order; Invalid for none or an unknown one."""
    unknown = [scope for scope in scopes if scope not in SERVICE_SCOPES]
    if unknown:
        raise Invalid(f"Unknown scope: {unknown[0]}")
    cleaned = [scope for scope in SERVICE_SCOPES if scope in scopes]
    if not cleaned:
        raise Invalid("A token needs at least one scope.")
    return cleaned


def issue_token(
    db: Session,
    actor: User,
    account_id: uuid.UUID,
    expires_at: datetime | None,
    *,
    scopes=INHERIT,
    allowed_ip_ranges=INHERIT,
) -> tuple[User, OrganizationMember, ServiceToken, str, ServiceToken | None]:
    """
    Make the account's token, or renew it: the token it had keeps working for 24 hours, and
    one already in its overlap from an earlier renewal is revoked (one at a time).

    Returns the account and its membership, the new token's row, the token itself (to show once) and the token
    it replaced, if any. `expires_at` is naive UTC, in the future, or None.

    Phase 10.2 — `scopes` (a non-empty list of `SERVICE_SCOPES`) and `allowed_ip_ranges`
    (normalized CIDRs; None or empty: any address). Left as `INHERIT`, a renewal keeps the
    replaced token's, and a first token gets every scope and any address.
    """
    mine = ensure_owner(db, actor)
    account, membership = get_account(db, mine, account_id)
    now = datetime.utcnow()
    if expires_at is not None and expires_at <= now:
        raise Invalid("The expiry must be in the future.")
    if scopes is not INHERIT:
        scopes = _clean_scopes(scopes or [])

    replaced = None
    for row in live_tokens(db, account, now):
        if row.replaced_at is None:
            row.replaced_at = now
            replaced = row
        else:  # an older one still in its overlap: only one at a time
            row.revoked_at = now
            row.revoked_by_user_id = actor.id

    if scopes is INHERIT:
        scopes = list(replaced.scopes or []) if replaced is not None else every_scope()
    if allowed_ip_ranges is INHERIT:
        allowed_ip_ranges = replaced.allowed_ip_ranges if replaced is not None else None
    token, prefix = new_service_token()
    row = ServiceToken(
        service_account_id=account.id,
        prefix=prefix,
        token_hash=hash_api_key(token),
        expires_at=expires_at,
        created_by_user_id=actor.id,
        created_at=now,
        scopes=scopes,
        allowed_ip_ranges=list(allowed_ip_ranges) if allowed_ip_ranges else None,
    )
    db.add(row)
    db.flush()
    if replaced is None:
        log_event(
            "service_token.created",
            actor_id=str(actor.id),
            service_account_id=str(account.id),
            token_id=str(row.id),
            expires=expires_at is not None,
        )
        _audit(db, actor, account, mine.organization_id, "service_token.created", token_id=row.id)
    else:
        log_event(
            "service_token.renewed",
            actor_id=str(actor.id),
            service_account_id=str(account.id),
            token_id=str(row.id),
            replaced_token_id=str(replaced.id),
            expires=expires_at is not None,
        )
        _audit(
            db,
            actor,
            account,
            mine.organization_id,
            "service_token.renewed",
            token_id=row.id,
            detail={"replaced_token_id": str(replaced.id)},
        )
    return account, membership, row, token, replaced


def _revoke(
    db: Session, actor: User, account: User, organization_id: uuid.UUID, *, old_only: bool
) -> list[ServiceToken]:
    now = datetime.utcnow()
    revoked = []
    for row in live_tokens(db, account, now):
        if old_only and row.replaced_at is None:
            continue
        row.revoked_at = now
        row.revoked_by_user_id = actor.id
        revoked.append(row)
    db.flush()
    if revoked:
        log_event(
            "service_token.revoked",
            actor_id=str(actor.id),
            service_account_id=str(account.id),
            token_ids=[str(row.id) for row in revoked],
            old_only=old_only,
        )
        for row in revoked:  # one row per token: the audit's target is the token
            _audit(db, actor, account, organization_id, "service_token.revoked", token_id=row.id)
    return revoked


def revoke_tokens(
    db: Session, actor: User, account_id: uuid.UUID, *, old_only: bool = False
) -> list[ServiceToken]:
    """End every token of the account at once; with `old_only`, just the one in its overlap."""
    mine = ensure_owner(db, actor)
    account, _ = get_account(db, mine, account_id)
    return _revoke(db, actor, account, mine.organization_id, old_only=old_only)


# ---------------------------------------------------------------- Warnings (Phase 10.2)


def token_warnings(row: ServiceToken, now: datetime | None = None) -> list[str]:
    """
    Why the active token needs attention, at `now` (naive UTC): `expires_soon`, it stops
    working within 14 days; `unused`, nothing has used it for 90 days (`last_used_at`, or
    `created_at` if never used). None for a token in its overlap after a renewal (it ends
    within a day anyway) or one that no longer works.
    """
    now = now or datetime.utcnow()
    if row.replaced_at is not None or not row.is_valid(now):
        return []
    warnings = []
    if row.expires_at is not None and row.expires_at - now <= EXPIRES_SOON:
        warnings.append(EXPIRES_SOON_WARNING)
    if now - (row.last_used_at or row.created_at) >= UNUSED_FOR:
        warnings.append(UNUSED_WARNING)
    return warnings


def attention_count(db: Session, organization_id: uuid.UUID, now: datetime | None = None) -> int:
    """How many of the organization's live tokens have a warning: the menu's dot, for owners
    and admins."""
    now = now or datetime.utcnow()
    rows = (
        db.query(ServiceToken)
        .join(User, User.id == ServiceToken.service_account_id)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(
            OrganizationMember.organization_id == organization_id,
            User.kind == SERVICE,
            User.is_active.is_(True),
            ServiceToken.revoked_at.is_(None),
            ServiceToken.replaced_at.is_(None),
        )
        .all()
    )
    return sum(1 for row in rows if token_warnings(row, now))


# ---------------------------------------------------------------- The audit, read (Phase 10.2)


def audit_page(
    db: Session,
    organization_id: uuid.UUID,
    *,
    account_id: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: int = 50,
) -> tuple[list[AuditEvent], datetime | None]:
    """
    The organization's audit, newest first: up to `limit` rows strictly older than `before`
    (naive UTC), and the cursor for the next page (None: no more). Rows of a removed account
    stay readable. A page never ends between two rows of the same instant, so `before` skips
    none: it ends before them, or, when they alone fill it, takes them all.
    """
    query = db.query(AuditEvent).filter(AuditEvent.organization_id == organization_id)
    if account_id is not None:
        query = query.filter(AuditEvent.service_account_id == account_id)
    if before is not None:
        query = query.filter(AuditEvent.at < before)
    rows = query.order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit + 1).all()
    if len(rows) <= limit:
        return rows, None
    page, boundary = rows[:limit], rows[limit].at
    if page[-1].at == boundary:
        earlier = [row for row in page if row.at != boundary]
        if earlier:
            page = earlier
        else:  # one instant fills the page: all of it, then older
            page = query.filter(AuditEvent.at == boundary).order_by(AuditEvent.id.desc()).all()
    return page, page[-1].at


# ---------------------------------------------------------------- Acting on behalf of a person


@dataclass(frozen=True)
class Acting:
    """Who a request acts as: the link's creator, and the service account behind it, if any."""

    creator: User
    service: User | None = None
    token_id: uuid.UUID | None = None
    on_behalf_of: User | None = None

    def event_fields(self) -> dict:
        """For the `url.*` events, when a service did it: ids only, never the email."""
        if self.service is None:
            return {}
        return {
            "service_account_id": str(self.service.id),
            "token_id": str(self.token_id) if self.token_id else None,
            "on_behalf_of": str(self.on_behalf_of.id) if self.on_behalf_of else None,
        }


def _header(request: Request) -> str | None:
    value = request.headers.get(ON_BEHALF_HEADER)
    return None if value is None else value.strip()


def _person_in_organization(db: Session, service: User, email: str) -> User | None:
    membership = get_membership(db, service)
    if membership is None or not email:
        return None
    return (
        db.query(User)
        .join(OrganizationMember, OrganizationMember.user_id == User.id)
        .filter(
            func.lower(User.email) == email.lower(),
            User.kind == PERSON,
            User.is_active.is_(True),
            OrganizationMember.organization_id == membership.organization_id,
        )
        .first()
    )


def _refuse_from_a_person(user: User, request: Request) -> None:
    if not user.is_service and _header(request) is not None:
        raise CodedHTTPException(
            403,
            ON_BEHALF_OF_NOT_ALLOWED,
            f"Only a service account's token may send {ON_BEHALF_HEADER}.",
        )


def acting_for(db: Session, request: Request, user: User) -> Acting:
    """
    Who a request that creates links acts as.

    - A person (session or API key): themselves. With the header, a 403
      (`on_behalf_of_not_allowed`): otherwise anyone could attribute links to someone else.
    - A service token without the header: the service account itself (jobs that act for
      nobody).
    - A service token with an email of an active person of its organization: that person, the
      service and the token. Anyone else, a 422 (`on_behalf_of_unknown`): they sign in to
      Shurly once, then it works.
    """
    _refuse_from_a_person(user, request)
    if not user.is_service:
        return Acting(creator=user)
    token = getattr(request.state, "service_token", None)
    token_id = token.id if token is not None else None
    email = _header(request)
    if not email:
        return Acting(creator=user, service=user, token_id=token_id)
    person = _person_in_organization(db, user, email)
    if person is None:
        raise CodedHTTPException(
            422,
            ON_BEHALF_OF_UNKNOWN,
            f"{ON_BEHALF_HEADER} names nobody in the organization. They sign in to Shurly once, "
            "then links can be made for them.",
        )
    return Acting(creator=person, service=user, token_id=token_id, on_behalf_of=person)


def acting_on_change(db: Session, request: Request, user: User) -> Acting:
    """
    For a change (PATCH, DELETE, tags): the header is accepted from a service token and goes
    into the event, but changes no creator and grants nothing: the service account's own role
    decides. An email nobody in the organization has is logged as no one. From a person, the
    same 403 as on create.
    """
    _refuse_from_a_person(user, request)
    if not user.is_service:
        return Acting(creator=user)
    token = getattr(request.state, "service_token", None)
    email = _header(request)
    person = _person_in_organization(db, user, email) if email else None
    return Acting(
        creator=user,
        service=user,
        token_id=token.id if token is not None else None,
        on_behalf_of=person,
    )
