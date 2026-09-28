"""
Phase 3.14.2 — the organization's members and the rules for their roles.

Roles rank member < admin < owner:
- Owners change the roles of admins and members, to any role (owner included).
  They never change another owner's role: owners step down themselves.
- Admins change no roles; they remove members.
- Nobody removes, or changes the role of, someone whose role is equal to or
  above theirs.
- Anyone may lower their own role, except the last owner: there is always at
  least one. That check locks the owner rows, so two owners stepping down at
  once can't both pass it.
- The first owner comes from `settings.bootstrap_owner_email`.
- Once someone has been removed, an owner can move their personal links and
  campaigns to the organization, so the team keeps them, then or later: the
  removed people are listed with what they still own.

These functions flush but don't commit: the caller owns the transaction.
"""

from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from server.core.config import settings
from server.core.models import URL, Campaign, Organization, OrganizationMember, OrgRole, User
from server.utils.event_log import log_event

_RANK = {OrgRole.MEMBER: 0, OrgRole.ADMIN: 1, OrgRole.OWNER: 2}


class OrganizationError(Exception):
    """A change the rules don't allow."""


class NotAMember(OrganizationError):
    """The person isn't in the organization."""


class NotAllowed(OrganizationError):
    """The actor's role doesn't allow the change."""


class LastOwner(OrganizationError):
    """The change would leave the organization without an owner."""


class CannotRemoveSelf(OrganizationError):
    """Removing yourself isn't done here."""


class StillActive(OrganizationError):
    """The person's account is still open."""


def get_or_create_default_organization(db: Session) -> Organization:
    """The organization every account belongs to (one at launch)."""
    organization = db.query(Organization).order_by(Organization.created_at).first()
    if organization is None:
        organization = Organization(
            name=settings.organization_name,
            google_domain=settings.organization_domain or None,
        )
        db.add(organization)
        db.flush()
    return organization


def get_membership(db: Session, user: User) -> OrganizationMember | None:
    return db.query(OrganizationMember).filter(OrganizationMember.user_id == user.id).first()


def _is_bootstrap_owner(user: User) -> bool:
    configured = settings.bootstrap_owner_email.strip().lower()
    return bool(configured) and user.email.lower() == configured


def _active_owners(db: Session, organization_id: UUID, lock: bool = False):
    query = (
        db.query(OrganizationMember)
        .join(User, User.id == OrganizationMember.user_id)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == OrgRole.OWNER,
            User.is_active.is_(True),
        )
    )
    if lock:
        query = query.with_for_update(of=OrganizationMember)
    return query.all()


def on_organization_domain(email: str) -> bool:
    """
    Whether `email` is on `settings.organization_domain`: an exact, case-insensitive
    match of the part after the last "@". An empty setting lets any address in.

    Exact on purpose: `evilgriddo.io`, `griddo.io.evil.com` and even `eu.griddo.io`
    are other domains. Sign-up is still open to anyone (retro R1, until 3.13), and
    members see every organization link and campaign — campaigns carry their
    recipients' names and emails — so this is what keeps a stranger out.
    """
    domain = settings.organization_domain.strip().lower()
    if not domain:
        return True
    return email.rsplit("@", 1)[-1].strip().lower() == domain


def join_default_organization(db: Session, user: User) -> OrganizationMember | None:
    """
    A new account joins as member, or as owner if it's the configured first owner
    and none is left. An account off the organization's email domain doesn't join
    (None): it keeps working, with only its own personal links.
    """
    existing = get_membership(db, user)
    if existing is not None:
        return existing
    if not on_organization_domain(user.email):
        # user_id only: the address itself is personal data.
        log_event("org.join_refused", user_id=str(user.id), reason="email_domain")
        return None
    organization = get_or_create_default_organization(db)
    role = OrgRole.MEMBER
    if _is_bootstrap_owner(user) and not _active_owners(db, organization.id):
        role = OrgRole.OWNER
    membership = OrganizationMember(organization_id=organization.id, user_id=user.id, role=role)
    db.add(membership)
    db.flush()
    return membership


def ensure_memberships(db: Session) -> None:
    """
    At startup: active accounts without a membership join the organization, and if
    no active owner is left, the configured first owner becomes one (break-glass).
    Inactive accounts stay out: that's what removing someone left them as.
    """
    organization = get_or_create_default_organization(db)
    members = db.query(OrganizationMember.user_id)
    for user in db.query(User).filter(User.is_active.is_(True), ~User.id.in_(members)).all():
        join_default_organization(db, user)

    if not settings.bootstrap_owner_email or _active_owners(db, organization.id):
        return
    owner = (
        db.query(User)
        .filter(
            func.lower(User.email) == settings.bootstrap_owner_email.strip().lower(),
            User.is_active.is_(True),
        )
        .first()
    )
    membership = get_membership(db, owner) if owner else None
    if membership is not None:
        before = membership.role
        membership.role = OrgRole.OWNER
        db.flush()
        _log_role_change(None, membership, before, reason="bootstrap_owner_email")


def _log_role_change(actor: User | None, membership: OrganizationMember, before: OrgRole, **extra):
    log_event(
        "org.role_changed",
        actor_id=str(actor.id) if actor else None,
        user_id=str(membership.user_id),
        from_role=before.value,
        to_role=membership.role.value,
        **extra,
    )


def _memberships(db: Session, actor: User, target_user_id: UUID):
    """The actor's membership and the target's, in the same organization."""
    mine = get_membership(db, actor)
    if mine is None:
        raise NotAllowed("You don't belong to an organization.")
    theirs = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.user_id == target_user_id,
            OrganizationMember.organization_id == mine.organization_id,
        )
        .first()
    )
    if theirs is None:
        raise NotAMember("That person isn't in your organization.")
    return mine, theirs


def _ensure_another_owner(db: Session, leaving: OrganizationMember) -> None:
    owners = _active_owners(db, leaving.organization_id, lock=True)
    if not any(owner.user_id != leaving.user_id for owner in owners):
        raise LastOwner("Make someone else owner first: an organization needs at least one.")


def change_role(
    db: Session, actor: User, target_user_id: UUID, new_role: OrgRole
) -> OrganizationMember:
    mine, theirs = _memberships(db, actor, target_user_id)
    if theirs.user_id == mine.user_id:
        if _RANK[new_role] > _RANK[mine.role]:
            raise NotAllowed("Nobody raises their own role.")
    elif mine.role != OrgRole.OWNER:
        raise NotAllowed("Only owners change roles.")
    elif theirs.role == OrgRole.OWNER:
        raise NotAllowed("Owners step down themselves.")

    if theirs.role == OrgRole.OWNER and new_role != OrgRole.OWNER:
        _ensure_another_owner(db, theirs)
    before = theirs.role
    theirs.role = new_role
    db.flush()
    if before != new_role:
        _log_role_change(actor, theirs, before)
    return theirs


def transfer_ownership(db: Session, actor: User, target_user_id: UUID) -> OrganizationMember:
    """Make someone owner and step down to admin, in one change."""
    mine, theirs = _memberships(db, actor, target_user_id)
    if mine.role != OrgRole.OWNER:
        raise NotAllowed("Only owners hand the role over.")
    if theirs.user_id == mine.user_id:
        raise NotAllowed("You're already an owner.")
    if not theirs.user.is_active:
        raise NotAMember("That account is closed.")

    before = theirs.role
    theirs.role = OrgRole.OWNER
    db.flush()
    _log_role_change(actor, theirs, before)
    mine.role = OrgRole.ADMIN
    db.flush()
    _log_role_change(actor, mine, OrgRole.OWNER)
    return theirs


def remove_member(db: Session, actor: User, target_user_id: UUID) -> None:
    """Take someone out of the organization and close their account (one organization at launch)."""
    if target_user_id == actor.id:
        raise CannotRemoveSelf("You can't remove yourself.")
    mine, theirs = _memberships(db, actor, target_user_id)
    if mine.role == OrgRole.MEMBER or _RANK[theirs.role] >= _RANK[mine.role]:
        raise NotAllowed("You can only remove people below your role.")

    user = theirs.user
    user.is_active = False
    user.clear_api_key()
    role = theirs.role
    db.delete(theirs)
    db.flush()
    log_event("org.member_removed", actor_id=str(actor.id), user_id=str(user.id), role=role.value)


def removed_members(db: Session, actor: User) -> list[tuple[User, int, int]]:
    """
    The people removed from the organization, each with how many personal links (a
    campaign's included) and campaigns they still own: what `adopt_personal_links` would
    move. Most first, then by email. Owners only, as the move is.

    Removing someone closes their account (one organization at launch), so these are the
    closed accounts on the organization's email domain. One off the domain was never in
    it, whatever closed it, and its address isn't the owners' to see.
    """
    mine = get_membership(db, actor)
    if mine is None or mine.role != OrgRole.OWNER:
        raise NotAllowed("Only owners see who was removed.")
    # Their profiles (Phase 3.12: names) in one more query, not one per person.
    closed = (
        db.query(User).options(selectinload(User.profile)).filter(User.is_active.is_(False)).all()
    )
    people = [user for user in closed if on_organization_domain(user.email)]
    if not people:
        return []

    ids = [user.id for user in people]
    owned = {}
    for model in (URL, Campaign):
        owned[model] = dict(
            db.query(model.created_by, func.count(model.id))
            .filter(model.created_by.in_(ids), model.organization_id.is_(None))
            .group_by(model.created_by)
            .all()
        )
    rows = [(user, owned[URL].get(user.id, 0), owned[Campaign].get(user.id, 0)) for user in people]
    rows.sort(key=lambda row: (-(row[1] + row[2]), row[0].email.lower(), row[0].email))
    return rows


def adopt_personal_links(db: Session, actor: User, target_user_id: UUID) -> tuple[int, int]:
    """
    Move a removed person's personal links and campaigns to the actor's organization.

    Returns how many links (a campaign's included) and campaigns moved. One
    organization at launch, so any closed account is someone who left it.
    """
    mine = get_membership(db, actor)
    if mine is None or mine.role != OrgRole.OWNER:
        raise NotAllowed("Only owners move someone's personal links to the organization.")
    target = db.get(User, target_user_id)
    if target is None:
        raise NotAMember("That person isn't in your organization.")
    if target.is_active:
        raise StillActive("Remove them from the organization first.")

    moved = {}
    for model in (URL, Campaign):
        moved[model] = (
            db.query(model)
            .filter(model.created_by == target.id, model.organization_id.is_(None))
            .update({model.organization_id: mine.organization_id}, synchronize_session=False)
        )
    db.flush()
    log_event(
        "org.links_adopted",
        actor_id=str(actor.id),
        user_id=str(target.id),
        links=moved[URL],
        campaigns=moved[Campaign],
    )
    return moved[URL], moved[Campaign]
