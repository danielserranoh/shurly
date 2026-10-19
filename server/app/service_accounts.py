"""
Phase 10.1 — managing service accounts and their tokens (`_pm/spec_service_accounts.md`).

For the organization's owner, signed in (`get_signed_in_session`: a session, not an API key
or a service token); its admins read them. A member, or someone outside the organization,
gets a 403; a service account that isn't the organization's, a 404. The rules live in
`server/utils/service_accounts.py`. None of these is an MCP tool (mcp_server/server.py): an
assistant reading untrusted text must not be talked into minting a token.

A token is returned once, when it's made or renewed: Shurly keeps only its hash, and shows its
prefix (`shsa_<prefix>`) afterwards.

Phase 10.2: a token's `scopes` and `allowed_ip_ranges` are set when it's made or renewed (a
renewal keeps the replaced token's unless the request sets them), its `warnings` are shown with
it, and `GET /service-accounts/audit` reads what the accounts did and what was done to them.
"""

import uuid as uuid_pkg
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session, selectinload

from server.app.urls import _click_counts, _to_url_response
from server.core import get_db
from server.core.auth import SignedInSession, get_signed_in_session
from server.core.models import URL, AuditEvent, OrgRole, ServiceToken, User
from server.schemas.datetimes import as_utc
from server.schemas.responses import get_responses
from server.schemas.service_account import (
    AuditEventItem,
    AuditPage,
    AuditPerson,
    AuditServiceAccount,
    ResponsiblePerson,
    ServiceAccountCreate,
    ServiceAccountResponse,
    ServiceAccountUpdate,
    ServiceTokenCreate,
    ServiceTokenInfo,
    ServiceTokenIssued,
)
from server.schemas.url import URLListResponse
from server.utils import service_accounts as service
from server.utils.access import viewer
from server.utils.bounds import MAX_SKIP
from server.utils.people import names

service_accounts_router = APIRouter()

_STATUS = {
    service.NotAllowed: status.HTTP_403_FORBIDDEN,
    service.NotFound: status.HTTP_404_NOT_FOUND,
    service.Invalid: status.HTTP_422_UNPROCESSABLE_ENTITY,
}


def _http_error(exc: service.ServiceAccountError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


def _token_info(row: ServiceToken | None, now: datetime | None = None) -> ServiceTokenInfo | None:
    if row is None:
        return None
    return ServiceTokenInfo(
        id=row.id,
        prefix=row.shown_prefix,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        valid_until=row.overlap_ends_at,
        scopes=list(row.scopes or []),
        allowed_ip_ranges=list(row.allowed_ip_ranges or []),
        warnings=service.token_warnings(row, now),
    )


def _account_response(db: Session, account: User, role: OrgRole):
    live = service.live_tokens(db, account)
    active = next((row for row in live if row.replaced_at is None), None)
    previous = next((row for row in live if row.replaced_at is not None), None)
    person = account.responsible
    first, last = names(person)
    return ServiceAccountResponse(
        id=account.id,
        display_name=account.display_name or "",
        description=account.description,
        role=role.value,
        responsible=ResponsiblePerson(
            user_id=person.id, email=person.email, first_name=first, last_name=last
        )
        if person is not None
        else None,
        created_at=account.created_at,
        token=_token_info(active),
        previous_token=_token_info(previous),
    )


@service_accounts_router.get(
    "", response_model=list[ServiceAccountResponse], responses=get_responses(401, 403)
)
def list_service_accounts(
    session: SignedInSession = Depends(get_signed_in_session), db: Session = Depends(get_db)
):
    """
    The organization's service accounts, by name: each one's role, person responsible, and its
    token's prefix, `created_at`, `expires_at` and `last_used_at` (never the token). Owners and
    admins, signed in.
    """
    try:
        mine = service.ensure_reader(db, session.user)
    except service.ServiceAccountError as exc:
        raise _http_error(exc) from exc
    return [
        _account_response(db, account, role)
        for account, role in service.accounts_of(db, mine.organization_id)
    ]


# Declared before the `/{account_id}` routes, so `audit` is never read as an id.
@service_accounts_router.get(
    "/audit", response_model=AuditPage, responses=get_responses(401, 403, 422)
)
def list_service_account_audit(
    account: uuid_pkg.UUID | None = Query(None, description="Only this service account's events"),
    before: datetime | None = Query(
        None, description="Only events strictly older than this (the previous page's `next_before`)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Maximum number of events (1-200)"),
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    What the organization's service accounts did (links, campaigns, tags, redirect rules, and
    for whom) and what was done to them (made, changed, removed; tokens made, renewed,
    revoked), newest first, kept 2 years. Page with `before=<next_before>`. People are named as
    they are now: someone deleted shows as `deleted`. Owners and admins, signed in.
    """
    try:
        mine = service.ensure_reader(db, session.user)
    except service.ServiceAccountError as exc:
        raise _http_error(exc) from exc
    if before is not None:
        before = as_utc(before).replace(tzinfo=None)  # naive UTC, as the column
    rows, next_before = service.audit_page(
        db, mine.organization_id, account_id=account, before=before, limit=limit
    )
    return AuditPage(items=_audit_items(db, session.user, rows), next_before=next_before)


def _as_uuid(value) -> uuid_pkg.UUID | None:
    try:
        return value if isinstance(value, uuid_pkg.UUID) else uuid_pkg.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _audit_items(db: Session, reader: User, rows: list[AuditEvent]) -> list[AuditEventItem]:
    """The rows, with the people, accounts and links they name looked up now: in one query each."""
    user_ids = {
        user_id
        for row in rows
        for user_id in (row.service_account_id, row.actor_id, row.on_behalf_of_id)
        if user_id is not None
    }
    users = {
        user.id: user
        for user in (
            db.query(User).options(selectinload(User.profile)).filter(User.id.in_(user_ids)).all()
            if user_ids
            else []
        )
    }
    url_ids = {
        url_id
        for row in rows
        if row.target_type == "url" and (url_id := _as_uuid(row.target_id)) is not None
    }
    short_codes = dict(
        db.query(URL.id, URL.short_code)
        .filter(URL.id.in_(url_ids), viewer(db, reader).sees(URL))
        .all()
        if url_ids
        else []
    )

    def person(user_id) -> AuditPerson | None:
        if user_id is None:
            return None
        user = users.get(user_id)
        if user is None:
            return AuditPerson(id=user_id, deleted=True)
        name = " ".join(part for part in names(user) if part) or None
        return AuditPerson(id=user.id, email=user.email, name=name)

    def account(user_id) -> AuditServiceAccount:
        user = users.get(user_id)
        if user is None:
            return AuditServiceAccount(id=user_id, deleted=True)
        return AuditServiceAccount(id=user.id, display_name=user.display_name)

    return [
        AuditEventItem(
            id=row.id,
            at=row.at,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            short_code=short_codes.get(_as_uuid(row.target_id))
            if row.target_type == "url"
            else None,
            detail=row.detail,
            service_account=account(row.service_account_id),
            token_id=row.token_id,
            actor=person(row.actor_id),
            on_behalf_of=person(row.on_behalf_of_id),
        )
        for row in rows
    ]


@service_accounts_router.post(
    "",
    response_model=ServiceAccountResponse,
    status_code=status.HTTP_201_CREATED,
    responses=get_responses(401, 403, 422),
)
def create_service_account(
    body: ServiceAccountCreate,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Make a service account: its name, what it's for, the person responsible (someone in the
    organization) and its role, `member` (default) or `admin`. It has no token yet: make one
    with `POST /service-accounts/{id}/token`. The owner, signed in.
    """
    try:
        account, membership = service.create_account(
            db,
            session.user,
            display_name=body.display_name,
            description=body.description,
            responsible_user_id=body.responsible_user_id,
            role=body.role,
        )
    except service.ServiceAccountError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return _account_response(db, account, membership.role)


@service_accounts_router.patch(
    "/{account_id}",
    response_model=ServiceAccountResponse,
    responses=get_responses(401, 403, 404, 422),
)
def update_service_account(
    account_id: uuid_pkg.UUID,
    body: ServiceAccountUpdate,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """Change its display name, description, person responsible or role. The owner, signed in."""
    try:
        account, membership = service.update_account(
            db, session.user, account_id, body.model_dump(exclude_unset=True)
        )
    except service.ServiceAccountError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return _account_response(db, account, membership.role)


@service_accounts_router.delete(
    "/{account_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=get_responses(401, 403, 404),
)
def remove_service_account(
    account_id: uuid_pkg.UUID,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Revoke its tokens and remove it from the organization. Its links keep working and keep
    its name ("via …"). The owner, signed in.
    """
    try:
        service.remove_account(db, session.user, account_id)
    except service.ServiceAccountError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@service_accounts_router.post(
    "/{account_id}/token",
    response_model=ServiceTokenIssued,
    status_code=status.HTTP_201_CREATED,
    responses=get_responses(401, 403, 404, 422),
)
def issue_service_token(
    account_id: uuid_pkg.UUID,
    body: ServiceTokenCreate | None = None,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Make the account's token, or renew it: the token it had keeps working for 24 hours, so the
    service can switch without failing requests (`DELETE …/token?old_only=true` ends it sooner).
    Optional `expires_at`, in the future. Optional `scopes` (at least one) and
    `allowed_ip_ranges` (CIDRs; empty or null: any address): left out, a first token gets every
    scope and any address, and a renewal keeps those of the token it replaces. The owner,
    signed in.

    The response has the token, `shsa_<prefix>_<secret>`, this once: Shurly keeps only its hash.
    """
    expires_at = body.expires_at if body else None
    if expires_at is not None:
        expires_at = as_utc(expires_at).replace(tzinfo=None)  # naive UTC, as the columns
    settings = body.settings_sent() if body else {}
    try:
        account, membership, row, token, replaced = service.issue_token(
            db, session.user, account_id, expires_at, **settings
        )
    except service.ServiceAccountError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    info = _token_info(row)
    return ServiceTokenIssued(
        **info.model_dump(),
        token=token,
        renewed=replaced is not None,
        service_account=_account_response(db, account, membership.role),
    )


@service_accounts_router.delete(
    "/{account_id}/token",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=get_responses(401, 403, 404),
)
def revoke_service_token(
    account_id: uuid_pkg.UUID,
    old_only: bool = Query(
        False, description="End only the renewed token still in its 24-hour overlap"
    ),
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Revoke every token of the account, at once: the next request with one is a 401. With
    `?old_only=true`, only the one still in its overlap after a renewal. The owner, signed in.
    """
    try:
        service.revoke_tokens(db, session.user, account_id, old_only=old_only)
    except service.ServiceAccountError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@service_accounts_router.get(
    "/{account_id}/links",
    response_model=URLListResponse,
    responses=get_responses(401, 403, 404, 422),
)
def list_service_account_links(
    account_id: uuid_pkg.UUID,
    token_id: uuid_pkg.UUID | None = Query(
        None, description="Only the links this token created: what a leaked token touched"
    ),
    skip: int = Query(0, ge=0, le=MAX_SKIP, description="Number of links to skip"),
    limit: int = Query(100, ge=1, le=100, description="Maximum number of links (1-100)"),
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    The links the service account created, newest first, also those it made for a person;
    with `token_id`, only those that token created. Owners and admins, signed in.

    Phase 10.3 — the links it manages show their destination to owners only: an admin gets it
    masked (`https://host/…`), as everywhere else.
    """
    try:
        mine = service.ensure_reader(db, session.user)
        account, _ = service.get_account(db, mine, account_id)
    except service.ServiceAccountError as exc:
        raise _http_error(exc) from exc
    who = viewer(db, session.user)
    query = db.query(URL).filter(URL.via_service_account_id == account.id, who.sees(URL))
    if token_id is not None:
        query = query.filter(URL.via_token_id == token_id)
    urls = (
        query.options(
            selectinload(URL.tags),
            selectinload(URL.creator).selectinload(User.profile),
            selectinload(URL.campaign),
            selectinload(URL.via_service_account),
        )
        .order_by(URL.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    total = query.offset(0).limit(None).count()
    counts = _click_counts(db, [url.id for url in urls])
    # Phase 10.3 — `_to_url_response` masks what `who` may not read (`destination_for`).
    return URLListResponse(
        urls=[_to_url_response(url, counts.get(url.id, 0), who) for url in urls], total=total
    )
