"""
Phase 3.14.3 — who sees and who changes which links and campaigns.

A link or campaign belongs to the organization (`organization_id` set) or only
to its creator (personal, `organization_id` NULL):
- See: your organization's, and your own personal ones.
- Change or delete: the ones you created, and your organization's if you're an
  admin or owner.

Someone else's personal link stays hidden (404), so nobody learns it exists. An
organization link you can see but not change is a 403.

Phase 10.1 — a service account is a viewer like a person, with its own role (member or
admin). It also changes the links it created on someone's behalf (`via_service_account_id`):
their creator is the person, and the service still has to set their expiry or revoke them.
Its links always belong to the organization, never to it alone.

Phase 10.3 — a link made through a service account is managed by it (server/utils/managed.py):
only that account changes it (`can_change`, the path every changing route takes), with a 403
`managed_link_protected` for anyone else, owners included. Its tags are the exception: they
change by the tags path (`can_change_tags`, `to_change="tags"`), which keeps the rule above for
every link, managed or not.

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
from server.utils import managed
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
        """
        May change or delete it: its destination, code, validity, cap, rules, preview and
        visibility (the locked fields). A managed link (10.3): only its manager. Otherwise its
        creator, the service account that made it, and the organization's admins and owners.
        """
        if managed.is_managed(item):
            return managed.is_manager(self, item)
        return self._is_creator_or_admin(item)

    def can_change_tags(self, item) -> bool:
        """
        May change its tags, the one thing people change on a managed link (10.3). The rule
        from before managed links, for every link: its creator (on a managed link, the person
        it was made for), the service account that made it (the manager), and the
        organization's admins and owners. Nobody gains or loses tags by a link being managed.
        """
        return self._is_creator_or_admin(item)

    def _is_creator_or_admin(self, item) -> bool:
        if item.created_by == self.user.id:
            return True
        # Phase 10.1 — the service account that created a link (campaigns have no such column).
        via = getattr(item, "via_service_account_id", None)
        if via is not None and via == self.user.id:
            return True
        return (
            item.organization_id is not None
            and item.organization_id == self.organization_id
            and self.role in (OrgRole.ADMIN, OrgRole.OWNER)
        )

    def ensure_can_change(self, item, noun: str = "link") -> None:
        """`can_change`, or a 403: `managed_link_protected` (naming its manager) on a managed
        link, the plain one otherwise."""
        managed.ensure_may_change(self, item)
        if not self.can_change(item):
            raise _not_yours(noun)

    def ensure_can_change_tags(self, item, noun: str = "link") -> None:
        """`can_change_tags`, or the plain 403."""
        if not self.can_change_tags(item):
            raise _not_yours(noun)

    def organization_for(self, visibility: Visibility) -> UUID | None:
        """The `organization_id` for something this person creates. A service account's are
        always the organization's (10.1): a personal one only its creator would see."""
        if self.user.is_service:
            return self.organization_id
        return None if visibility == "personal" else self.organization_id


def _not_yours(noun: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Only its creator, or an admin or owner, can change this {noun}.",
    )


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
    to_change: bool | Literal["tags"] = False,
) -> URL:
    """
    The link a code names on `domain` (`find_url`, Phase 8.3), if the person can see it:
    404 otherwise. With `to_change=True`, a 403 if they may see it but not change it
    (`ensure_can_change`: on a managed link, only its manager). With `to_change="tags"`, the
    same for its tags (`ensure_can_change_tags`), which people may still change on a managed
    link.
    """
    who = viewer(db, user)
    url = find_url(db, who, short_code, domain)
    if not url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="URL not found")
    if to_change == "tags":
        who.ensure_can_change_tags(url)
    elif to_change:
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
