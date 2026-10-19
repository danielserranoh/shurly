"""
Phase 10.3 — links managed by their service account (`_board/plan_managed-links-propuestas.md`).

A link made through a service account (`urls.via_service_account_id`) belongs to the system
that made it, e.g. Griddo Propuestas: a person deleting it or changing its destination leaves
that system pointing at a dead or different link. So:

- **Managed:** `via_service_account_id` is set and the link isn't a campaign link. A campaign
  link a service account made stays a campaign link, changed through its campaign.
- **Its manager** is that service account. A removed or deactivated one still manages: its
  links stay protected, and only an owner's audited override deletes them.
- **Changing it:** only the manager (`ensure_may_change`). People may still change its tags,
  by the tags path in server/utils/access.py (`Viewer.can_change_tags`).
- **Its destination** often carries a credential (Propuestas' access token): the manager and
  the owners of the link's organization see it, everyone else a mask (`destination_for`).

The rule is derived from data that already exists, so there is no column and no migration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import status
from sqlalchemy import and_, or_

from server.core.models import URL, OrgRole
from server.core.models.url import URLType
from server.utils.errors import MANAGED_LINK_PROTECTED, CodedHTTPException

if TYPE_CHECKING:
    from server.utils.access import Viewer

MASK = "…"


def is_managed(url) -> bool:
    """Made through a service account, and not a campaign link. Anything without the columns
    (a campaign) isn't managed."""
    return (
        getattr(url, "via_service_account_id", None) is not None
        and getattr(url, "url_type", None) != URLType.CAMPAIGN
    )


def manager_id(url) -> UUID | None:
    """The service account managing the link, or None when it isn't managed."""
    return url.via_service_account_id if is_managed(url) else None


def is_manager(viewer: Viewer, url) -> bool:
    """The viewer is the service account managing this link."""
    managing = manager_id(url)
    return managing is not None and viewer.user.id == managing


def sees_destination(viewer: Viewer, url) -> bool:
    """Everyone sees an ordinary link's destination. A managed link's: its manager, and an
    owner of the link's organization; not admins, members, the person it was made for or
    other service accounts."""
    if not is_managed(url):
        return True
    if is_manager(viewer, url):
        return True
    return (
        viewer.role == OrgRole.OWNER
        and viewer.organization_id is not None
        and viewer.organization_id == url.organization_id
    )


def masked(destination) -> str:
    """
    The destination's scheme and host (and port), its path and query hidden:
    `https://propuestas.griddo.io/p/abc?t=x` → `https://propuestas.griddo.io/…`. Credentials
    in the authority (`user:pass@`) are dropped. Never raises: anything without a scheme and
    a host becomes `…`.
    """
    try:
        parts = urlsplit(destination)
        scheme, host = parts.scheme, parts.hostname
        if not scheme or not host:
            return MASK
        if ":" in host:  # IPv6
            host = f"[{host}]"
        port = parts.port  # ValueError when it isn't a number in range
        authority = f"{host}:{port}" if port is not None else host
        return f"{scheme.lower()}://{authority}/{MASK}"
    except (TypeError, ValueError, AttributeError):
        return MASK


def destination_for(viewer: Viewer, url) -> str:
    """The destination this viewer may read: the real one, or its mask."""
    return url.original_url if sees_destination(viewer, url) else masked(url.original_url)


def _manager_name(url) -> str | None:
    """The managing service account's name, never raising (a detached link, say)."""
    try:
        account = url.via_service_account
    except Exception:  # noqa: BLE001 — a message's wording is never worth an error
        return None
    return getattr(account, "display_name", None) or None


def protected_message(url) -> str:
    name = _manager_name(url)
    who = name or "the integration that made it (a service account)"
    return f"This link is managed by {who}. Change or delete it from there."


def protected_error(url) -> CodedHTTPException:
    """The 403 `managed_link_protected` for a person changing a managed link."""
    return CodedHTTPException(
        status.HTTP_403_FORBIDDEN, MANAGED_LINK_PROTECTED, protected_message(url)
    )


def ensure_may_change(viewer: Viewer, url) -> None:
    """
    A managed link changes only through its manager: anyone else, owners included, gets the
    403 `managed_link_protected` (owners delete through the audited override route). Nothing
    for an ordinary link: the usual rule is `Viewer.ensure_can_change`'s.
    """
    if is_managed(url) and not is_manager(viewer, url):
        raise protected_error(url)


def managed_clause():
    """SQL condition: the URL rows that are managed."""
    return and_(URL.via_service_account_id.isnot(None), URL.url_type != URLType.CAMPAIGN)


def not_managed_clause():
    """SQL condition: the URL rows that aren't managed."""
    return or_(URL.via_service_account_id.is_(None), URL.url_type == URLType.CAMPAIGN)
