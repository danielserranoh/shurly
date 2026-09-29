"""
Phase 3.14.3 — who sees and who changes which links and campaigns.

A link or campaign belongs to the organization (`organization_id` set) or only
to its creator (personal, `organization_id` NULL):
- See: your organization's, and your own personal ones.
- Change or delete: the ones you created, and your organization's if you're an
  admin or owner.

Someone else's personal link stays hidden (404), so nobody learns it exists. An
organization link you can see but not change is a 403.

Every route that reads one link or campaign decides with `visible_url_or_404` or
`visible_campaign_or_404`, so a route can't answer for more people than another
(docs/PERSONAL_DATA.md, checked by tests/test_personal_data_inventory.py).
"""

from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload

from server.core.models import URL, Campaign, Domain, OrgRole, User
from server.utils.domain import normalize_hostname
from server.utils.organization import get_membership

Visibility = Literal["organization", "personal"]


@dataclass(frozen=True)
class Viewer:
    user: User
    organization_id: UUID | None
    role: OrgRole | None

    def sees(self, model):
        """SQL condition for the rows of `model` (URL or Campaign) this person can see."""
        own_personal = and_(model.organization_id.is_(None), model.created_by == self.user.id)
        if self.organization_id is None:
            return own_personal
        return or_(model.organization_id == self.organization_id, own_personal)

    def can_change(self, item) -> bool:
        if item.created_by == self.user.id:
            return True
        return (
            item.organization_id is not None
            and item.organization_id == self.organization_id
            and self.role in (OrgRole.ADMIN, OrgRole.OWNER)
        )

    def ensure_can_change(self, item, noun: str = "link") -> None:
        if not self.can_change(item):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Only its creator, or an admin or owner, can change this {noun}.",
            )

    def organization_for(self, visibility: Visibility) -> UUID | None:
        """The `organization_id` for something this person creates."""
        return None if visibility == "personal" else self.organization_id


def viewer(db: Session, user: User) -> Viewer:
    membership = get_membership(db, user)
    return Viewer(
        user=user,
        organization_id=membership.organization_id if membership else None,
        role=membership.role if membership else None,
    )


# Phase 8.3 — the `?domain=` of every route that takes a link's code.
LinkDomain = Annotated[
    str | None,
    Query(
        description="The link's domain, e.g. go.griddo.io: a code can name links on several "
        "domains. Without it, the default domain's link.",
    ),
]


def find_url(db: Session, who: Viewer, short_code: str, domain: str | None = None) -> URL | None:
    """
    Phase 8.3 — the link a code names, among the ones `who` sees. One code can name links
    on several domains. `domain` picks one, read like a request's Host header
    (`normalize_hostname`); without it, the default domain's link answers, then the other
    domains' by hostname. A link from before domains (no `domain_id`) counts as the
    default domain's, after one that has it.
    """
    return find_urls(db, who, [(short_code, domain)]).get((short_code, domain))


def visible_url_or_404(
    db: Session,
    user: User,
    short_code: str,
    domain: str | None = None,
    *,
    to_change: bool = False,
) -> URL:
    """
    The link a code names on `domain` (`find_url`, Phase 8.3), if the person can see it:
    404 otherwise. With `to_change`, a 403 if they may see it but not change it.
    """
    who = viewer(db, user)
    url = find_url(db, who, short_code, domain)
    if not url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    if to_change:
        who.ensure_can_change(url)
    return url


def visible_campaign_or_404(
    db: Session, user: User, campaign_id: UUID | str, *, to_change: bool = False
) -> Campaign:
    """
    A campaign the person can see: their organization's, whatever their role, or their own
    personal one. A 400 for a string that isn't a UUID, a 404 when they can't see it. With
    `to_change`, a 403 if they may see it but not change it.
    """
    if isinstance(campaign_id, str):
        try:
            campaign_id = UUID(campaign_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid campaign ID format"
            ) from exc
    who = viewer(db, user)
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id, who.sees(Campaign)).first()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    if to_change:
        who.ensure_can_change(campaign, noun="campaign")
    return campaign


def find_urls(
    db: Session, who: Viewer, addresses: list[tuple[str, str | None]], *options
) -> dict[tuple[str, str | None], URL]:
    """`find_url` for many (code, domain) addresses in one query; `options` load more, such
    as the tags. The addresses nothing answers are left out."""
    codes = {code for code, _ in addresses}
    candidates = (
        db.query(URL)
        .options(joinedload(URL.domain), *options)
        .filter(URL.short_code.in_(codes), who.sees(URL))
        .all()
    )
    default = db.query(Domain.hostname).filter(Domain.is_default.is_(True)).scalar()
    by_code: dict[str, list[URL]] = {}
    for url in candidates:
        by_code.setdefault(url.short_code, []).append(url)
    found = {}
    for code, domain in addresses:
        links = by_code.get(code, [])
        if domain is not None:
            hostname = normalize_hostname(domain)
            links = [
                url for url in links if (url.domain.hostname if url.domain else default) == hostname
            ]
        if links:
            found[(code, domain)] = min(links, key=_default_domain_first)
    return found


def _default_domain_first(url: URL) -> tuple:
    return (
        not (url.domain is None or url.domain.is_default),
        url.domain is None,
        url.domain.hostname if url.domain else "",
        url.created_at,
        str(url.id),
    )
