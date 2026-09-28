"""
Phase 3.13.2 — which account a Google sign-in opens, and the flow's short-lived
secrets.

Accounts are recognised by Google's `sub`, which survives an email rename:

1. A known identity (provider + `sub`) opens its account. A new address from
   Google updates the identity's email; `users.email` stays, since it's the JWT
   subject (a recycled address must not inherit live sessions).
2. First sign-in, and no account has the address: a new one, without a password,
   which joins the organization (the domain gate of 3.14.2 still applies).
3. First sign-in, and an account has the address but no Google identity (made by
   the open sign-up before 3.13): it's linked. Nobody verified that address, so
   whoever made the account may not be the person Google vouches for: its
   password is cleared, its API key revoked and its sessions ended (account
   pre-hijacking, 3.13.3).
4. First sign-in, and the address's account is linked to another `sub`: refused,
   never linked. Google may have given a freed address to someone else.

A closed account (removed from the organization) is refused either way.

Phase 3.12 — the names in the ID token fill a profile that has neither name yet;
names the person set are never replaced. A name the profile would refuse is left out.

Secrets are stored as SHA-256 digests (the PKCE verifier excepted), used once and
short-lived; expired rows are purged when new ones are made. These functions
flush but don't commit: the caller owns the transaction.
"""

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from server.core.models import GoogleAuthState, LoginCode, User, UserIdentity, UserProfile
from server.utils.event_log import log_event
from server.utils.google_oidc import GoogleAccount, GoogleSignInError, new_code_verifier
from server.utils.organization import join_default_organization
from server.utils.profile import NAME_MAX_LENGTH, clean_name

PROVIDER = "google"
STATE_TTL = timedelta(minutes=10)
LOGIN_CODE_TTL = timedelta(seconds=60)


def _digest(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> datetime:
    return datetime.utcnow()  # naive UTC, as the columns store it


def start_sign_in(db: Session) -> tuple[str, str]:
    """A new sign-in: the `state` to send to Google, and the PKCE verifier."""
    db.execute(delete(GoogleAuthState).where(GoogleAuthState.expires_at < _now()))
    state, verifier = secrets.token_urlsafe(32), new_code_verifier()
    db.add(
        GoogleAuthState(
            state_hash=_digest(state), code_verifier=verifier, expires_at=_now() + STATE_TTL
        )
    )
    db.flush()
    return state, verifier


def take_code_verifier(db: Session, state: str) -> str | None:
    """
    The PKCE verifier of the sign-in `state` belongs to, which uses the state up.
    None if it's unknown, used or expired. One DELETE … RETURNING, so two requests
    racing with the same state can't both get it.
    """
    row = db.execute(
        delete(GoogleAuthState)
        .where(GoogleAuthState.state_hash == _digest(state))
        .returning(GoogleAuthState.code_verifier, GoogleAuthState.expires_at)
    ).first()
    if row is None or row.expires_at <= _now():
        return None
    return row.code_verifier


def sign_in_with_google(db: Session, account: GoogleAccount) -> User:
    """The account `account` opens, made or linked if needed. Raises GoogleSignInError."""
    identity = (
        db.query(UserIdentity)
        .filter(UserIdentity.provider == PROVIDER, UserIdentity.subject == account.subject)
        .first()
    )
    if identity is not None:
        user = identity.user
        if not user.is_active:
            raise GoogleSignInError("inactive", user_id=str(user.id))
        if identity.email != account.email:
            identity.email = account.email
            db.flush()
        _fill_names(db, user, account)
        return user

    user = db.query(User).filter(func.lower(User.email) == account.email).first()
    if user is None:
        user = User(email=account.email, password_hash=None, is_active=True)
        db.add(user)
        db.flush()
    elif not user.is_active:
        raise GoogleSignInError("inactive", user_id=str(user.id))
    elif user.has_google:
        raise GoogleSignInError("account_conflict", user_id=str(user.id))
    else:
        _lock_out_whoever_made_it(db, user)

    db.add(
        UserIdentity(
            user_id=user.id, provider=PROVIDER, subject=account.subject, email=account.email
        )
    )
    db.flush()
    # A new account joins; an existing one that never did (it predates 3.14) joins now.
    join_default_organization(db, user)
    _fill_names(db, user, account)
    return user


def _fill_names(db: Session, user: User, account: GoogleAccount) -> None:
    """Phase 3.12 — Google's names, for a profile without either."""
    first, last = _name(account.given_name), _name(account.family_name)
    if first is None and last is None:
        return
    profile = user.profile
    if profile is None:
        profile = UserProfile(user=user)
        db.add(profile)
    elif profile.first_name or profile.last_name:
        return
    profile.first_name, profile.last_name = first, last
    db.flush()


def _name(value: str | None) -> str | None:
    """A name from Google as the profile would take it; None when it wouldn't."""
    try:
        name = clean_name(value)
    except ValueError:
        return None
    return name if isinstance(name, str) and len(name) <= NAME_MAX_LENGTH else None


def _lock_out_whoever_made_it(db: Session, user: User) -> None:
    """An account made with an address nobody verified: take back every way in."""
    password_cleared = user.password_hash is not None
    api_key_revoked = user.has_api_key
    user.password_hash = None
    user.clear_api_key()
    user.sessions_valid_from = _now()
    db.flush()
    log_event(
        "auth.identity_linked",
        user_id=str(user.id),
        provider=PROVIDER,
        password_cleared=password_cleared,
        api_key_revoked=api_key_revoked,
    )


def issue_login_code(db: Session, user: User) -> str:
    """The one-time code the frontend trades for a JWT, within LOGIN_CODE_TTL."""
    db.execute(delete(LoginCode).where(LoginCode.expires_at < _now()))
    code = secrets.token_urlsafe(32)
    db.add(LoginCode(code_hash=_digest(code), user_id=user.id, expires_at=_now() + LOGIN_CODE_TTL))
    db.flush()
    return code


def redeem_login_code(db: Session, code: str) -> User | None:
    """The account a one-time code was issued to, which uses it up; None if it's no good."""
    row = db.execute(
        delete(LoginCode)
        .where(LoginCode.code_hash == _digest(code))
        .returning(LoginCode.user_id, LoginCode.expires_at)
    ).first()
    if row is None or row.expires_at <= _now():
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user
