"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import (
    SignedInSession,
    authenticate_user,
    create_access_token,
    get_current_user,
    get_signed_in_session,
    hash_password,
    new_api_key,
    verify_password,
)
from server.core.config import settings
from server.core.models import User, UserProfile
from server.schemas.auth import (
    APIKeyResponse,
    ChangePasswordRequest,
    SetPasswordRequest,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)
from server.schemas.profile import ProfileResponse, ProfileUpdate
from server.schemas.responses import MessageResponse, get_responses
from server.utils import rate_limit
from server.utils.event_log import log_event
from server.utils.organization import join_default_organization
from server.utils.rate_limit import LOGIN_FAILURES_PER_ACCOUNT

auth_router = APIRouter()


@auth_router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "User successfully created"},
        **get_responses(400, 422),
    },
    # Phase 3.13.2 — out of the API docs, and so of the MCP tools, unless it's on.
    include_in_schema=settings.allow_password_signup,
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user.

    Creates a new user account with the provided email and password.

    Phase 3.13.2: off unless `ALLOW_PASSWORD_SIGNUP` is on (local development and
    tests only). Accounts come from signing in with Google.

    **Request Body:**
    - **email**: Valid email address (required)
    - **password**: Password with minimum 8 characters (required)

    **Responses:**
    - **201**: User successfully created - Returns user information
    - **400**: Email already registered
    - **404**: Sign-up with a password is off
    - **422**: Validation error (invalid email format, password too short, etc.)
    """
    # Read per request, so tests can turn it on.
    if not settings.allow_password_signup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    # Check if user already exists
    existing_user = db.query(User).filter(User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Create new user
    user = User(
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        is_active=True,
    )

    db.add(user)
    db.flush()
    # Phase 3.14.2 — every account belongs to the organization.
    join_default_organization(db, user)
    db.commit()
    db.refresh(user)

    return user


@auth_router.post(
    "/login",
    response_model=Token,
    responses={
        200: {"description": "Login successful - Returns JWT access token"},
        **get_responses(401, 422),
    },
)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password.

    Authenticates user credentials and returns a JWT access token.

    **Request Body:**
    - **email**: User's email address (required)
    - **password**: User's password (required)

    **Responses:**
    - **200**: Login successful - Returns JWT access token valid for 7 days
    - **401**: Incorrect email or password
    - **422**: Validation error (invalid email format, missing fields, etc.)
    """
    # Phase 6.3 — failed attempts per account (the per-IP limit is the middleware's).
    # Only failures count, so the right password isn't counted with a guesser's; the
    # address needn't have an account, so a 429 tells nothing about who has one.
    # check() then hit() isn't atomic: guesses sent at the same moment can all pass
    # check() and overshoot the limit by a few. The per-IP limit bounds how many.
    account = user_data.email.strip().lower()
    locked = rate_limit.check(LOGIN_FAILURES_PER_ACCOUNT, account)
    if not locked.allowed:
        log_event(
            "http.rate_limited", path="/api/v1/auth/login", limit=LOGIN_FAILURES_PER_ACCOUNT.name
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {locked.retry_after} seconds, "
            "or sign in with Google.",
            headers={"Retry-After": str(locked.retry_after)},
        )

    user = authenticate_user(db, user_data.email, user_data.password)

    if not user:
        rate_limit.hit(LOGIN_FAILURES_PER_ACCOUNT, account)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token = create_access_token(data={"sub": user.email})
    # Phase 3.13.2 — who still signs in with a password, before enforcing Google (3.13.4).
    log_event("auth.login", method="password", user_id=str(user.id))

    return {"access_token": access_token, "token_type": "bearer"}


@auth_router.get(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "Returns current user information"},
        **get_responses(401),
    },
)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current user information.

    Returns the authenticated user's profile information.

    **Authentication:** Required (JWT Bearer token)

    **Responses:**
    - **200**: Successfully retrieved user information
    - **401**: Authentication required or invalid token
    """
    return current_user


@auth_router.patch(
    "/me/profile",
    response_model=ProfileResponse,
    responses={
        200: {"description": "The profile, as saved"},
        **get_responses(401, 422),
    },
)
def update_my_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Update your profile: first name, last name, country and time zone (Phase 3.12).

    Only the fields sent change; `null` (or a blank name) clears one. `GET /auth/me`
    returns the profile under `profile`.

    - **country**: ISO 3166-1 alpha-2 code, e.g. `ES`
    - **timezone**: IANA name, e.g. `Europe/Madrid` or `Atlantic/Canary`, never an offset.
      A legacy name is stored as the current one (`Asia/Calcutta` → `Asia/Kolkata`)

    **Responses:**
    - **200**: The profile, as saved
    - **401**: Authentication required or invalid token
    - **422**: A field it can't take, e.g. an unknown country code or time zone
    """
    changes = body.model_dump(exclude_unset=True)
    profile = current_user.profile
    if not changes:
        return profile or ProfileResponse()
    if profile is None:
        profile = UserProfile(user=current_user)
        db.add(profile)
    for field, value in changes.items():
        setattr(profile, field, value)
    db.commit()
    return profile


@auth_router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Password changed successfully"},
        **get_responses(400, 401, 403, 409, 422),
    },
)
def change_password(
    password_data: ChangePasswordRequest,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Change user password.

    Updates the user's password after verifying the current password.

    **Authentication:** A signed-in session (JWT Bearer token). An API key gets a 403, even
    with the current password: a leaked key must not become a password.

    **Request Body:**
    - **current_password**: User's current password (required)
    - **new_password**: New password with minimum 8 characters (required)

    **Responses:**
    - **200**: Password changed successfully
    - **400**: Current password is incorrect
    - **401**: Authentication required or invalid token
    - **403**: An API key
    - **409**: The account has no password yet (set one with `PUT /api/v1/auth/password`)
    - **422**: Validation error (new password too short, etc.)
    """
    current_user = session.user
    if current_user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account has no password yet. Set one with PUT /api/v1/auth/password.",
        )

    # Verify current password
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Update password
    current_user.password_hash = hash_password(password_data.new_password)
    db.commit()

    return {"message": "Password changed successfully"}


def _reauth_required(message: str) -> HTTPException:
    """Phase 3.13.3 — a 403 the frontend can act on: send the person through Google, retry."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "reauth_required", "message": message},
    )


@auth_router.put(
    "/password",
    response_model=MessageResponse,
    responses={
        200: {"description": "Password set"},
        **get_responses(400, 401, 403, 422),
    },
)
def set_password(
    body: SetPasswordRequest,
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Set or replace the password (Phase 3.13.3). Signed-in sessions only: an API key
    gets a 403.

    - With `current_password`, when the account has a password: it must match.
    - Without it: the account must sign in with Google (otherwise its password is
      the only proof of who this is), and the session must be at most 10 minutes
      old, so a stolen token can't mint a password that outlives it. That's the
      way back from a forgotten password: sign in with Google, set a new one.

    **Responses:**
    - **200**: Password set
    - **400**: Current password missing or incorrect
    - **401**: Authentication required or invalid token
    - **403**: An API key, or a session older than 10 minutes without `current_password`
    - **422**: Validation error (new password too short, etc.)
    """
    user = session.user
    if body.current_password is not None and user.password_hash is not None:
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current password is incorrect",
            )
    elif user.password_hash is not None and not user.has_google:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Give your current password to replace it.",
        )
    elif not session.is_fresh():
        raise _reauth_required("Sign in with Google again to set a password.")

    user.password_hash = hash_password(body.new_password)
    db.commit()
    log_event("auth.password_set", user_id=str(user.id))

    return {"message": "Password set"}


@auth_router.delete(
    "/password",
    response_model=MessageResponse,
    responses={
        200: {"description": "Password removed"},
        **get_responses(401, 403, 409),
    },
)
def remove_password(
    session: SignedInSession = Depends(get_signed_in_session),
    db: Session = Depends(get_db),
):
    """
    Remove the password (Phase 3.13.3), leaving sign in with Google. Signed-in
    sessions only (an API key gets a 403), at most 10 minutes old, so a stolen
    token can't take the owner's password away.

    **Responses:**
    - **200**: Password removed, or there was none
    - **401**: Authentication required or invalid token
    - **403**: An API key, or a session older than 10 minutes (`reauth_required`)
    - **409**: The account doesn't sign in with Google: it would have no way in
    """
    user = session.user
    if not user.has_google:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sign in with Google once first: without a password, this account "
            "would have no way in.",
        )
    if not session.is_fresh():
        raise _reauth_required("Sign in with Google again to remove the password.")

    if user.password_hash is not None:
        user.password_hash = None
        db.commit()
        log_event("auth.password_removed", user_id=str(user.id))

    return {"message": "Password removed"}


@auth_router.post(
    "/api-key/generate",
    response_model=APIKeyResponse,
    responses={
        200: {"description": "API key generated successfully"},
        **get_responses(401),
    },
)
def generate_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate a new API key for the current user.

    Creates a new API key for programmatic access. This will replace any existing API key.

    **Authentication:** Required (JWT Bearer token)

    **Responses:**
    - **200**: API key generated successfully - Returns the new API key
    - **401**: Authentication required or invalid token

    **Note:** The API key is shown only this once: Shurly keeps a hash of it, not
    the key (Phase 6.3). Save it securely.
    """
    api_key = new_api_key()

    # Phase 3.9.6 — set scope explicitly. Only FULL_ACCESS is enforced today; other
    # scope values are reserved so we can roll out roles without a destructive migration.
    from server.core.models import ApiKeyScope

    current_user.set_api_key(api_key)
    current_user.api_key_scope = ApiKeyScope.FULL_ACCESS
    current_user.api_key_constraints = None
    db.commit()

    return {"api_key": api_key, "scope": ApiKeyScope.FULL_ACCESS.value}


@auth_router.delete(
    "/api-key",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "API key revoked successfully"},
        **get_responses(401),
    },
)
def revoke_api_key(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Revoke the current user's API key.

    Deletes the user's API key, invalidating any programmatic access using it.

    **Authentication:** Required (JWT Bearer token)

    **Responses:**
    - **200**: API key revoked successfully
    - **401**: Authentication required or invalid token
    """
    current_user.clear_api_key()
    db.commit()

    return {"message": "API key revoked successfully"}
