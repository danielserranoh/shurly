"""
The suite runs on the database it was asked for (tests/conftest.py): in-memory SQLite by default,
PostgreSQL with TEST_SUITE_ON_POSTGRES=1. So CI's `test-postgres` job can't quietly run on SQLite.
"""

import os


def test_the_suite_runs_where_it_was_asked(db_session):
    asked = "postgresql" if os.getenv("TEST_SUITE_ON_POSTGRES") == "1" else "sqlite"

    assert db_session.get_bind().dialect.name == asked
