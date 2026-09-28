"""
Phase 3.14.3 — who sees and who changes which links and campaigns.

A link or campaign belongs to the organization (`organization_id` set) or only
to its creator (personal, `organization_id` NULL):
- See: your organization's, and your own personal ones.
- Change or delete: the ones you created, and your organization's if you're an
  admin or owner.

Someone else's personal link stays hidden (404), so nobody learns it exists. An
organization link you can see but not change is a 403.
"""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from server.core.models import OrgRole, User
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
