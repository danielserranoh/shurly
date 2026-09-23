"""Domain helpers — Phase 3.10.1."""

from __future__ import annotations

import logging

from sqlalchemy import exists, update
from sqlalchemy.orm import Session, aliased

from server.core.config import settings
from server.core.models import URL, Domain, URLType

logger = logging.getLogger(__name__)


def get_or_create_default_domain(db: Session) -> Domain:
    """
    Return the default domain row, creating it on first call.

    Idempotent: if the row exists with `is_default=True` we return it; otherwise
    we promote the configured `default_domain` hostname to default. Used both at
    startup seeding and as a fallback inside URL creation when no explicit domain
    is supplied (single-domain at launch).
    """
    existing = db.query(Domain).filter(Domain.is_default.is_(True)).first()
    if existing:
        return existing

    by_host = (
        db.query(Domain).filter(Domain.hostname == settings.default_domain).first()
    )
    if by_host:
        by_host.is_default = True
        db.commit()
        db.refresh(by_host)
        return by_host

    domain = Domain(hostname=settings.default_domain, is_default=True)
    db.add(domain)
    db.commit()
    db.refresh(domain)
    return domain


def resolve_domain_for_host(db: Session, host_header: str | None) -> Domain:
    """
    Map a request Host header to a Domain row, falling back to the default.

    The Host header may include a port (`shurl.griddo.io:8000`); we strip it
    before matching. Unknown hosts fall back to the default domain so existing
    short URLs keep working when a new vanity host points at the same backend
    but hasn't been registered yet.
    """
    if host_header:
        bare_host = host_header.split(":", 1)[0].strip().lower()
        match = db.query(Domain).filter(Domain.hostname == bare_host).first()
        if match:
            return match
    return get_or_create_default_domain(db)


def backfill_campaign_url_domains(db: Session) -> int:
    """
    Bind campaign URLs stored with a NULL `domain_id` to the default domain.

    The campaign generator used to leave `domain_id` NULL, so those rows escaped
    the `(domain_id, short_code)` UNIQUE (PostgreSQL treats NULLs as distinct)
    and the resolver's legacy fallback served them on every host. Idempotent, so
    it runs at every startup; returns the number of rows moved.

    A row stays NULL when moving it would violate the constraint: its code is
    already taken on the default domain, or another NULL-domain row shares it.
    Those keep resolving through the legacy fallback and are logged for review.
    """
    default = get_or_create_default_domain(db)
    other = aliased(URL)
    taken_on_default = exists().where(
        other.domain_id == default.id, other.short_code == URL.short_code
    )
    shared_with_legacy_row = exists().where(
        other.domain_id.is_(None), other.short_code == URL.short_code, other.id != URL.id
    )
    legacy = (URL.domain_id.is_(None), URL.url_type == URLType.CAMPAIGN)

    moved = db.execute(
        update(URL)
        .where(*legacy, ~taken_on_default, ~shared_with_legacy_row)
        # A repair, not an edit: keep updated_at as it was
        .values(domain_id=default.id, updated_at=URL.updated_at)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()

    left = db.query(URL).filter(*legacy).count()
    if left:
        logger.warning(
            f"{left} campaign URL(s) kept a NULL domain_id: their short code is taken on "
            f"{default.hostname} or shared with another NULL-domain row. They still resolve "
            "via the legacy fallback; review them by hand (query in CHANGELOG.md)."
        )
    return moved
