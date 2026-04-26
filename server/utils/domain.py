"""Domain helpers — Phase 3.10.1."""

from __future__ import annotations

from sqlalchemy.orm import Session

from server.core.config import settings
from server.core.models import Domain


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
