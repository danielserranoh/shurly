"""Authentication utilities for JWT and password handling."""

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.config import settings
from server.core.models import User

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer token scheme
security = HTTPBearer()

# bcrypt has a hard 72-byte input limit. bcrypt 5+ refuses longer inputs instead
# of silently truncating, so we truncate explicitly. Truncating at byte boundary
# (encode → slice → decode with errors="ignore") avoids splitting multibyte UTF-8.
_BCRYPT_MAX_BYTES = 72


def _truncate_for_bcrypt(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) <= _BCRYPT_MAX_BYTES:
        return password
    return encoded[:_BCRYPT_MAX_BYTES].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return pwd_context.hash(_truncate_for_bcrypt(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(_truncate_for_bcrypt(plain_password), hashed_password)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Dict containing the claims (e.g., {"sub": user_email})
        expires_delta: Optional custom expiration time

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> dict:
    """
    Decode and validate a JWT token.

    Args:
        token: The JWT token to decode

    Returns:
        Dict containing the token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


def get_user_by_api_key(db: Session, api_key: str) -> User | None:
    """
    Phase 5.4 — look up a user by their API key.

    Returns None for unknown / inactive accounts. Centralized here so both the
    FastAPI bearer dependency and the MCP token verifier share one code path.
    """
    if not api_key:
        return None
    user = db.query(User).filter(User.api_key == api_key).first()
    if user is None or not user.is_active:
        return None
    return user


def _looks_like_jwt(token: str) -> bool:
    """JWTs are dot-separated 3-part base64. API keys produced by
    `secrets.token_urlsafe(32)` never contain dots, so this is unambiguous."""
    return token.count(".") == 2


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    FastAPI dependency to get the current authenticated user.

    Accepts both JWT access tokens (issued by /auth/login) and API keys (issued
    by /auth/api-key/generate). The token shape disambiguates: JWTs have two
    dots, API keys never do. JWT validation runs first; if the token isn't a
    JWT we fall back to the API-key lookup.

    Usage in routes:
        @app.get("/protected")
        def protected_route(current_user: User = Depends(get_current_user)):
            ...
    """
    token = credentials.credentials

    if _looks_like_jwt(token):
        payload = decode_access_token(token)
        email: str | None = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
            )
        user = db.query(User).filter(User.email == email).first()
    else:
        user = get_user_by_api_key(db, token)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive",
        )

    return user


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """
    Authenticate a user by email and password.

    Args:
        db: Database session
        email: User email
        password: Plain text password

    Returns:
        User object if authentication succeeds, None otherwise
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user
