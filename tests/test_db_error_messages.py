"""
Database errors leave the SQL parameters out of their message.

SQLAlchemy ends a database error's message with the statement's bound
parameters, i.e. what the user sent, and every traceback in the logs prints
that message: uvicorn's for a failed API request, fastmcp's for a tool call.
The engine's `hide_parameters` swaps them for a placeholder. The statement
stays, so the error still says what failed.
"""

import traceback

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

EMAIL = "jane.doe@acme.example"


@pytest.fixture
def users_insert_fails(db_session):
    """Every INSERT INTO users fails in the database, as on a lost connection. A trigger in each
    dialect the suite runs on (tests/conftest.py): SQLite's, or PostgreSQL's, a function's."""
    postgres = db_session.get_bind().dialect.name == "postgresql"
    if postgres:
        db_session.execute(
            text(
                "CREATE FUNCTION reject_users() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'rejected' USING ERRCODE = 'integrity_constraint_violation'; "
                "END $$"
            )
        )
        db_session.execute(
            text(
                "CREATE TRIGGER reject_users BEFORE INSERT ON users "
                "FOR EACH ROW EXECUTE FUNCTION reject_users()"
            )
        )
    else:
        db_session.execute(
            text(
                "CREATE TRIGGER reject_users BEFORE INSERT ON users "
                "BEGIN SELECT RAISE(ABORT, 'rejected'); END"
            )
        )
    db_session.commit()
    try:
        yield
    finally:
        db_session.rollback()
        if postgres:
            db_session.execute(text("DROP TRIGGER reject_users ON users"))
            db_session.execute(text("DROP FUNCTION reject_users()"))
        else:
            db_session.execute(text("DROP TRIGGER reject_users"))
        db_session.commit()


def test_app_engine_hides_sql_parameters():
    from server.core import engine

    assert engine.hide_parameters


def test_failed_insert_leaves_the_values_out_of_the_traceback(
    client, users_insert_fails, allow_password_signup
):
    with pytest.raises(IntegrityError) as raised:
        client.post("/api/v1/auth/register", json={"email": EMAIL, "password": "horse-battery-9"})

    # What uvicorn logs for the request: the whole traceback, chained causes included.
    logged = "".join(traceback.format_exception(raised.value))
    assert EMAIL not in logged
    assert "$2b$" not in logged  # nor the password's bcrypt hash
    assert "INSERT INTO users" in logged  # the statement still says what failed
