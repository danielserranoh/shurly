"""Pytest configuration and fixtures."""

import os
import uuid

# Skip the FastAPI startup event (which tries to connect to PostgreSQL) during tests.
# Must be set before `from main import app` so the env var is read at app instantiation.
os.environ["TESTING"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.dialects.postgresql import UUID  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.ext.compiler import compiles  # noqa: E402
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
    hide_parameters=True,  # as the app's engine (server/core/__init__.py)
)


# Enable foreign keys for SQLite
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@compiles(UUID, "sqlite")
def _uuid_as_text_on_sqlite(type_, compiler, **kw):
    # SQLite gives a declared type of UUID numeric affinity, so a hex id that
    # looks like a number would be stored as REAL.
    return "CHAR(32)"


TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables once when the module loads
Base.metadata.create_all(bind=engine)


def pytest_addoption(parser):
    parser.addoption(
        "--require-mcp",
        action="store_true",
        help="Fail instead of skipping the MCP suites when the [mcp] extra is missing.",
    )
    parser.addoption(
        "--require-postgres",
        action="store_true",
        help="Fail instead of skipping the PostgreSQL suites when TEST_DATABASE_URL is unset.",
    )


def pytest_configure(config):
    # The MCP suites use `pytest.importorskip("fastmcp")`, so without the
    # extra they skip silently. CI passes --require-mcp so they can't.
    if config.getoption("--require-mcp"):
        try:
            import fastmcp  # noqa: F401
        except ImportError as exc:
            raise pytest.UsageError(
                "--require-mcp: fastmcp is not installed. Run `uv sync --extra mcp`."
            ) from exc
    # Same for the suites that need a real PostgreSQL (migrations): they skip
    # without TEST_DATABASE_URL, and CI passes --require-postgres.
    if config.getoption("--require-postgres") and not os.getenv("TEST_DATABASE_URL"):
        raise pytest.UsageError("--require-postgres: set TEST_DATABASE_URL to a PostgreSQL server.")


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
    from server.core.auth import hash_password

    user = User(
        email="test@example.com",
        password_hash=hash_password("test123"),
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


@pytest.fixture
def pg_engine():
    """A fresh, empty PostgreSQL database for one test (Phase 3.14; needs TEST_DATABASE_URL)."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set (a PostgreSQL server)")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"shurly_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    pg = create_engine(make_url(url).set(database=name))
    try:
        yield pg
    finally:
        pg.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
