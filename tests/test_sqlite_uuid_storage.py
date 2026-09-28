"""
UUIDs survive the in-memory SQLite of the test suite.

On SQLite, SQLAlchemy stores a UUID as its 32 hex digits. The models declare
PostgreSQL's `UUID`, a type SQLite gives numeric affinity, so an id whose hex
reads as a number (all digits, or digits around one `e`) was stored as a float
and failed to load: `'float' object has no attribute 'replace'`. About one
uuid4 in 700,000 does, which failed CI at random. `tests/conftest.py` makes
SQLite store them as text.
"""

import uuid

import pytest

from server.core.models import User


@pytest.mark.parametrize(
    "user_id",
    [
        uuid.UUID("12345678-1234-4234-8234-123456781234"),  # all digits
        uuid.UUID("12345678-1234-4234-8234-12345678e234"),  # digits around one e
    ],
    ids=["digits", "exponent"],
)
def test_numeric_looking_uuid_round_trips(db_session, user_id):
    user = User(id=user_id, email="a@b.c", password_hash="x", is_active=True)
    db_session.add(user)
    db_session.commit()

    db_session.refresh(user)

    assert user.id == user_id
