"""Authentication endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import (
    authenticate_user,
    create_access_token,
    get_current_user,
    hash_password,
)
from server.core.models import User
from server.schemas.auth import Token, UserLogin, UserRegister, UserResponse

auth_router = APIRouter()


@auth_router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Register a new user.

    - **email**: Valid email address
    - **password**: Password (min 8 characters)
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


@auth_router.post("/login", response_model=Token)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    Login with email and password.

    Returns a JWT access token valid for 7 days.
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


@auth_router.get("/me", response_model=UserResponse)
def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get current user information.

    Requires authentication.
    """
    return current_user
