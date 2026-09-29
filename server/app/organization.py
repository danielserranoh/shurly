"""
Phase 3.14.2 — the organization, its members and their roles.

The rules live in `server/utils/organization.py`; this module maps them to HTTP:
403 when the caller's role doesn't allow the change, 404 when the person isn't in
the organization, 409 when the change would leave it without an owner or needs
the person removed first.
"""

import uuid as uuid_pkg

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, contains_eager

from server.core import get_db
from server.core.auth import get_current_user
from server.core.models import Organization, OrganizationMember, User
from server.schemas.organization import (
    AdoptedLinks,
    LinksAdoption,
    MemberResponse,
    OrganizationResponse,
    OwnershipTransfer,
    RemovedMember,
    RoleUpdate,
)
from server.schemas.responses import get_responses
from server.utils import organization as org_service
from server.utils.people import names

organization_router = APIRouter()

_LAST_OWNER = {409: {"description": "The change would leave the organization without an owner"}}

_STATUS = {
    org_service.NotAllowed: status.HTTP_403_FORBIDDEN,
    org_service.NotAMember: status.HTTP_404_NOT_FOUND,
    org_service.LastOwner: status.HTTP_409_CONFLICT,
    org_service.CannotRemoveSelf: status.HTTP_400_BAD_REQUEST,
    org_service.StillActive: status.HTTP_409_CONFLICT,
}


def _http_error(exc: org_service.OrganizationError) -> HTTPException:
    return HTTPException(status_code=_STATUS[type(exc)], detail=str(exc))


def _names(user: User) -> dict:
    """Phase 3.12 — first and last name from the profile; None without one."""
    first, last = names(user)
    return {"first_name": first, "last_name": last}


def _member_response(membership: OrganizationMember) -> MemberResponse:
    return MemberResponse(
        user_id=membership.user_id,
        email=membership.user.email,
        **_names(membership.user),
        role=membership.role,
        joined_at=membership.joined_at,
    )


def _my_membership(db: Session, user: User) -> OrganizationMember:
    membership = org_service.get_membership(db, user)
    if membership is None:
        raise HTTPException(status_code=404, detail="You don't belong to an organization.")
    return membership


@organization_router.get("", response_model=OrganizationResponse, responses=get_responses(401, 404))
def get_organization(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The caller's organization, and their role in it."""
    membership = _my_membership(db, current_user)
    organization = db.get(Organization, membership.organization_id)
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        google_domain=organization.google_domain,
        role=membership.role,
    )


@organization_router.get(
    "/members", response_model=list[MemberResponse], responses=get_responses(401, 404)
)
def list_organization_members(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Everyone in the caller's organization, with their role."""
    membership = _my_membership(db, current_user)
    members = (
        db.query(OrganizationMember)
        .join(User, User.id == OrganizationMember.user_id)
        # The users from the join, their profiles in one more query: none per member.
        .options(contains_eager(OrganizationMember.user).selectinload(User.profile))
        .filter(OrganizationMember.organization_id == membership.organization_id)
        .order_by(User.email)
        .all()
    )
    return [_member_response(member) for member in members]


@organization_router.patch(
    "/members/{user_id}",
    response_model=MemberResponse,
    responses={**get_responses(401, 403, 404, 422), **_LAST_OWNER},
)
def update_member_role(
    user_id: uuid_pkg.UUID,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Change someone's role. Owners change admins' and members' roles; anyone may
    lower their own, except the last owner.
    """
    try:
        membership = org_service.change_role(db, current_user, user_id, body.role)
    except org_service.OrganizationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return _member_response(membership)


@organization_router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=get_responses(400, 401, 403, 404),
)
def remove_organization_member(
    user_id: uuid_pkg.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove someone below your role and close their account (one organization at
    launch). Their links keep redirecting.
    """
    try:
        org_service.remove_member(db, current_user, user_id)
    except org_service.OrganizationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()


@organization_router.post(
    "/transfer-ownership",
    response_model=MemberResponse,
    responses={**get_responses(401, 403, 404, 422), **_LAST_OWNER},
)
def transfer_ownership(
    body: OwnershipTransfer,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Make someone owner and step down to admin, in one change."""
    try:
        membership = org_service.transfer_ownership(db, current_user, body.user_id)
    except org_service.OrganizationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return _member_response(membership)


@organization_router.get(
    "/removed-members", response_model=list[RemovedMember], responses=get_responses(401, 403)
)
def list_removed_members(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """
    The people removed from the organization, with how many personal links (a campaign's
    included) and campaigns each still owns: what adopt-personal-links would move. Most
    first, then by email. Owners only.
    """
    try:
        rows = org_service.removed_members(db, current_user)
    except org_service.OrganizationError as exc:
        raise _http_error(exc) from exc
    return [
        RemovedMember(
            user_id=user.id, email=user.email, **_names(user), links=links, campaigns=campaigns
        )
        for user, links, campaigns in rows
    ]


@organization_router.post(
    "/adopt-personal-links",
    response_model=AdoptedLinks,
    responses={
        **get_responses(401, 403, 404, 422),
        409: {"description": "The person is still in the organization: remove them first"},
    },
)
def adopt_personal_links(
    body: LinksAdoption,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Move the personal links and campaigns of someone who was removed to the
    organization, so the team keeps them. Owners only.
    """
    try:
        links, campaigns = org_service.adopt_personal_links(db, current_user, body.user_id)
    except org_service.OrganizationError as exc:
        db.rollback()
        raise _http_error(exc) from exc
    db.commit()
    return AdoptedLinks(links=links, campaigns=campaigns)
