"""
Phase 9.1 — the waitlist: people outside Griddo, who can't sign in (accounts come from Google
Workspace, 3.13), say they'd like Shurly, as an individual or for a company.

- `POST` is public. It validates every field (server/schemas/waitlist.py), needs consent to be
  contacted, and is limited per client IP (`RATE_LIMIT_WAITLIST_PER_IP`, server/utils/rate_limit.py).
  Every sign-up gets the same answer, whatever happened: a filled honeypot (`website`) stores
  nothing, and the same email again updates its entry. So the answer never says whether an email
  is listed, and echoes nothing back. The IP is never stored.
- The organization's owners and admins read the list, export it as a CSV and remove an entry when
  its person asks (`ensure_owner_or_admin`, server/utils/organization.py): anyone else gets a 403.
- None of it is an MCP tool (mcp_server/server.py): the sign-up is a public form, and the list is
  strangers' free text, which an assistant with write tools shouldn't read.

`waitlist.joined` is logged with the kind and the company size: never an email, a name or a company.
"""

import uuid as uuid_pkg
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import User, WaitlistEntry
from server.core.models.waitlist import COMPANY_SIZES, KINDS
from server.schemas.datetimes import utc_isoformat
from server.schemas.responses import get_responses
from server.schemas.waitlist import (
    WaitlistCounts,
    WaitlistEntryResponse,
    WaitlistJoin,
    WaitlistJoined,
    WaitlistListResponse,
)
from server.utils import organization as org_service
from server.utils.bounds import MAX_SKIP
from server.utils.csv_export import stream_csv
from server.utils.event_log import log_event

waitlist_router = APIRouter()

NOT_GIVEN = "not_given"
_FIELDS = ("name", "kind", "company", "company_size", "role", "use_case", "source")


@waitlist_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=WaitlistJoined,
    responses={
        201: {"description": "On the list: the same answer for every sign-up"},
        422: {"description": "A field is missing or invalid, or there's no consent"},
        429: {"description": "Too many sign-ups from this address"},
    },
)
def join_waitlist(body: WaitlistJoin, db: Session = Depends(get_db)):
    """
    Join the waitlist. Anyone may call it, without an account; limited per IP.

    A company needs its name. Consent to be contacted about Shurly is required. Signing up again
    with the same email updates the entry. The answer is the same whatever happened.
    """
    if body.website:
        log_event("waitlist.honeypot")
        return WaitlistJoined()
    _save(db, body)
    log_event("waitlist.joined", kind=body.kind, company_size=body.company_size)
    return WaitlistJoined()


def _save(db: Session, body: WaitlistJoin) -> None:
    """One entry per email: the answers given now, in a new entry or in the one there was."""
    now = datetime.utcnow()
    answers = {field: getattr(body, field) for field in _FIELDS}
    entry = db.query(WaitlistEntry).filter(WaitlistEntry.email == body.email).first()
    if entry is None:
        db.add(WaitlistEntry(email=body.email, consent_at=now, created_at=now, **answers))
        try:
            db.commit()
            return
        except IntegrityError:
            # The same email, from a sign-up that committed meanwhile: update that one.
            db.rollback()
            entry = db.query(WaitlistEntry).filter(WaitlistEntry.email == body.email).one()
    for field, value in answers.items():
        setattr(entry, field, value)
    entry.consent_at = now
    entry.updated_at = now
    db.commit()


def _reader(db: Session, user: User) -> None:
    try:
        org_service.ensure_owner_or_admin(db, user)
    except org_service.NotAllowed as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _counts(db: Session) -> WaitlistCounts:
    by_kind = dict(
        db.query(WaitlistEntry.kind, func.count(WaitlistEntry.id))
        .group_by(WaitlistEntry.kind)
        .all()
    )
    by_size = dict(
        db.query(WaitlistEntry.company_size, func.count(WaitlistEntry.id))
        .filter(WaitlistEntry.kind == "company")
        .group_by(WaitlistEntry.company_size)
        .all()
    )
    sizes = {size: by_size.get(size, 0) for size in COMPANY_SIZES}
    sizes[NOT_GIVEN] = by_size.get(None, 0)
    return WaitlistCounts(
        total=sum(by_kind.values()),
        **{kind: by_kind.get(kind, 0) for kind in KINDS},
        by_company_size=sizes,
    )


def _newest_first(db: Session):
    return db.query(WaitlistEntry).order_by(
        WaitlistEntry.created_at.desc(), WaitlistEntry.id.desc()
    )


@waitlist_router.get(
    "", response_model=WaitlistListResponse, responses=get_responses(401, 403, 422)
)
def list_waitlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0, le=MAX_SKIP, description="Entries to skip, for pagination"),
    limit: int = Query(50, ge=1, le=200, description="Entries to return (1-200)"),
):
    """
    The waitlist, newest first, with how many signed up: in all, as individuals and for
    companies, and the companies by size. Owners and admins of the organization.
    """
    _reader(db, current_user)
    counts = _counts(db)
    entries = _newest_first(db).offset(skip).limit(limit).all()
    return WaitlistListResponse(
        entries=[WaitlistEntryResponse.model_validate(entry) for entry in entries],
        total=counts.total,
        counts=counts,
    )


@waitlist_router.get(
    "/export",
    response_class=Response,
    responses={
        200: {"description": "Every entry, newest first", "content": {"text/csv": {}}},
        **get_responses(401, 403),
    },
)
def export_waitlist(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The whole waitlist as a CSV, newest first. Owners and admins of the organization."""
    _reader(db, current_user)
    rows = [
        (
            utc_isoformat(entry.created_at),
            entry.email,
            entry.name,
            entry.kind,
            entry.company,
            entry.company_size,
            entry.role,
            entry.use_case,
            entry.source,
            utc_isoformat(entry.consent_at),
        )
        for entry in _newest_first(db).all()
    ]
    return stream_csv(
        headers=[
            "created_at",
            "email",
            "name",
            "kind",
            "company",
            "company_size",
            "role",
            "use_case",
            "source",
            "consent_at",
        ],
        rows=rows,
        filename=f"shurly-waitlist-{datetime.utcnow():%Y-%m-%d}.csv",
    )


@waitlist_router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=get_responses(401, 403, 404),
)
def remove_waitlist_entry(
    entry_id: uuid_pkg.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove someone from the waitlist, when they ask. Owners and admins of the organization."""
    _reader(db, current_user)
    entry = db.get(WaitlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not on the waitlist.")
    db.delete(entry)
    db.commit()
    log_event("waitlist.removed", actor_id=str(current_user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
