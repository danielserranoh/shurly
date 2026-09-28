"""Authentication utilities for JWT and password handling."""

import calendar
from dataclasses import dataclass
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
    now = datetime.utcnow()

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)

    # Phase 3.13.3 — `iat` lets `sessions_valid_from` end older sessions, and the
    # password endpoints ask for a fresh one.
    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
    return encoded_jwt


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


# Phase 3.13.3 — how recent a sign-in must be to set a password without the current one.
FRESH_SESSION = timedelta(minutes=10)


@dataclass(frozen=True)
class SignedInSession:
    """A JWT and the account it's for. API keys never make one."""

    user: User
    issued_at: int | None  # the JWT's `iat`, in seconds; None before 3.13

    def is_fresh(self) -> bool:
        if self.issued_at is None:
            return False
        now = calendar.timegm(datetime.utcnow().utctimetuple())
        return now - self.issued_at <= FRESH_SESSION.total_seconds()


def _session_from_jwt(db: Session, token: str) -> SignedInSession | None:
    """
    The session a JWT stands for, or None: the token is invalid or expired, names
    no account, or was issued before the account's `sessions_valid_from`.

    Seconds, as `iat` is: a token from the cutoff's own second is kept, so the
    sign-in that set the cutoff keeps the session it just gave. Tokens without
    `iat` (issued before this release) are refused only once a cutoff is set.
    Active or not is the caller's call: the API answers 403, the MCP 401.
    """
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    email = payload.get("sub")
    if not email:
        return None
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        return None
    issued_at = payload.get("iat")
    if user.sessions_valid_from is not None:
        cutoff = calendar.timegm(user.sessions_valid_from.utctimetuple())
        if issued_at is None or issued_at < cutoff:
            return None
    return SignedInSession(user=user, issued_at=issued_at)


def get_user_by_jwt(db: Session, token: str) -> User | None:
    """The account a valid JWT is for (see `_session_from_jwt`). Shared with the MCP verifier."""
    session = _session_from_jwt(db, token)
    return session.user if session else None


def _credentials_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _inactive_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="User account is inactive",
    )


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
        user = get_user_by_jwt(db, token)
    else:
        user = get_user_by_api_key(db, token)

    if user is None:
        raise _credentials_error()

    if not user.is_active:
        raise _inactive_error()

    return user


def get_signed_in_session(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> SignedInSession:
    """
    Phase 3.13.3 — like `get_current_user`, for what only a signed-in person may
    do (managing the password). An API key gets a 403: a leaked key must not
    become a password.
    """
    token = credentials.credentials
    if not _looks_like_jwt(token):
        if get_user_by_api_key(db, token) is None:
            raise _credentials_error()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Sign in to do this: an API key can't manage passwords.",
        )
    session = _session_from_jwt(db, token)
    if session is None:
        raise _credentials_error()
    if not session.user.is_active:
        raise _inactive_error()
    return session


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

    # No account, or one made through Google with no password (3.13.3): nothing to
    # check, but spend the time a check takes. Answering faster would tell anyone
    # which addresses have an account.
    if user is None or user.password_hash is None:
        pwd_context.dummy_verify()
        return None

    if not verify_password(password, user.password_hash):
        return None

    return user
