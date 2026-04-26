"""Pytest configuration and fixtures."""

import os

# Skip the FastAPI startup event (which tries to connect to PostgreSQL) during tests.
# Must be set before `from main import app` so the env var is read at app instantiation.
os.environ["TESTING"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from main import app  # noqa: E402
from server.core import Base, get_db  # noqa: E402
from server.core.auth import create_access_token  # noqa: E402
from server.core.models import (  # noqa: E402, F401 - Import all models for SQLAlchemy
    URL,
    Campaign,
    Tag,
    User,
    Visitor,
)

# Use in-memory SQLite for testing with proper configuration
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

# Create engine with StaticPool to keep the in-memory database alive
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # Keep single connection alive for in-memory DB
)


# Enable foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables once when the module loads
Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    session = TestingSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        # Clean up data but keep tables
        session.close()
        # Rollback any uncommitted changes
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()


@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client with database override."""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def test_user(db_session: Session):
    """Create a test user."""
    # Pre-generated bcrypt hash for password "test123" to avoid bcrypt version issues
    # Generated with: passlib.hash.bcrypt.hash("test123")
    test_password_hash = "$2b$12$KIXxkzJLQw2xGfmC4y4pEeN.uD1QQZvZxPzJ6wJx.d8RQkLfC6fBu"

    user = User(
        email="test@example.com",
        password_hash=test_password_hash,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User):
    """Create authentication headers for test user."""
    access_token = create_access_token(data={"sub": test_user.email})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture(scope="function")
def init_predefined_tags(db_session: Session):
    """Initialize predefined tags for tests that need them."""
    from server.utils.tags import initialize_predefined_tags

    initialize_predefined_tags(db_session)
