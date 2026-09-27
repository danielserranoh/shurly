"""
Phase 3.14.1 — schema migrations with Alembic, run at startup.

`create_all()` only creates missing tables; it never adds a column to one that
exists. Alembic owns the schema from here on. These tests need a real
PostgreSQL (TEST_DATABASE_URL): migrations use its DDL, enum types and advisory
locks, none of which the in-memory SQLite of the other suites has.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from server.core import Base
from server.core.migrations import BASELINE_REVISION, alembic_config, run_migrations


def _head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def test_revisions_form_a_single_line():
    """Two branches that each add a revision leave two heads, and the app can't upgrade to both."""
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


@pytest.fixture
def pg_engine():
    """A fresh, empty PostgreSQL database for one test."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set (a PostgreSQL server)")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    name = f"shurly_test_{uuid.uuid4().hex[:12]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(make_url(url).set(database=name))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def _version(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _drift(engine) -> list:
    """What `alembic revision --autogenerate` would still write: models vs. database."""
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)


def test_empty_database_migrates_to_the_models(pg_engine):
    run_migrations(pg_engine)

    assert _version(pg_engine) == _head()
    # Fails when a model changes and nobody wrote the migration for it.
    assert _drift(pg_engine) == []


def test_database_from_before_alembic_is_stamped_then_upgraded(pg_engine):
    """Production: the baseline's tables, built by create_all(), and no alembic_version."""
    config = alembic_config()
    with pg_engine.begin() as conn:
        config.attributes["connection"] = conn
        command.upgrade(config, BASELINE_REVISION)
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(
            text(
                "INSERT INTO users (id, email, password_hash, api_key_scope, is_active, created_at)"
                " VALUES (:id, 'kept@griddo.io', 'x', 'FULL_ACCESS', true, now())"
            ),
            {"id": uuid.uuid4()},
        )

    run_migrations(pg_engine)

    assert _version(pg_engine) == _head()
    assert _drift(pg_engine) == []
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users")).scalar_one() == "kept@griddo.io"


def test_running_again_changes_nothing(pg_engine):
    run_migrations(pg_engine)
    run_migrations(pg_engine)

    assert _version(pg_engine) == _head()


def test_tasks_booting_together_migrate_once(pg_engine):
    """ECS starts tasks side by side: the lock lets one migrate while the others wait.

    Separate processes, like the tasks: Alembic keeps global state, so threads in
    one process would test Alembic rather than the database.
    """
    url = pg_engine.url.render_as_string(hide_password=False)
    boot = (
        "import sys; from sqlalchemy import create_engine;"
        " from server.core.migrations import run_migrations;"
        " run_migrations(create_engine(sys.argv[1]))"
    )
    tasks = [
        subprocess.Popen(
            [sys.executable, "-c", boot, url],
            cwd=Path(__file__).resolve().parent.parent,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(3)
    ]
    failures = []
    for task in tasks:
        _, stderr = task.communicate(timeout=120)
        if task.returncode != 0:
            lines = stderr.strip().splitlines()
            failures.append(next((line for line in reversed(lines) if "Error" in line), lines[-1]))

    assert failures == []
    assert _version(pg_engine) == _head()
