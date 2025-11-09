"""Authentication endpoints."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from server.core.models import User
from server.schemas.auth import (
    APIKeyResponse,
    ChangePasswordRequest,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)
from server.schemas.responses import MessageResponse, get_responses

auth_router = APIRouter()


@auth_router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "User successfully created"},
        **get_responses(400, 422),
    },
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user.

    Creates a new user account with the provided email and password.

    **Request Body:**
    - **email**: Valid email address (required)
    - **password**: Password with minimum 8 characters (required)

    **Responses:**
    - **201**: User successfully created - Returns user information
    - **400**: Email already registered
    - **422**: Validation error (invalid email format, password too short, etc.)
    """
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
    user = authenticate_user(db, user_data.email, user_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Create access token
    access_token = create_access_token(data={"sub": user.email})

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


@auth_router.post(
    "/change-password",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    responses={
        200: {"description": "Password changed successfully"},
        **get_responses(400, 401, 422),
    },
)
def change_password(
    password_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Change user password.

    Updates the user's password after verifying the current password.

    **Authentication:** Required (JWT Bearer token)

    **Request Body:**
    - **current_password**: User's current password (required)
    - **new_password**: New password with minimum 8 characters (required)

    **Responses:**
    - **200**: Password changed successfully
    - **400**: Current password is incorrect
    - **401**: Authentication required or invalid token
    - **422**: Validation error (new password too short, etc.)
    """
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

    **Note:** The API key is only shown once. Save it securely.
    """
    # Generate a secure random API key
    api_key = secrets.token_urlsafe(32)

    # Update user's API key
    current_user.api_key = api_key
    db.commit()

    return {"api_key": api_key}


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
    current_user.api_key = None
    db.commit()

    return {"message": "API key revoked successfully"}
