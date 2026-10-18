"""
Phase 3.14.1 — schema migrations with Alembic, run at startup.

`create_all()` only creates missing tables; it never adds a column to one that
exists. Alembic owns the schema from here on. These tests need a real
PostgreSQL (TEST_DATABASE_URL): migrations use its DDL, enum types and advisory
locks, none of which the in-memory SQLite of the other suites has.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, DateTime, MetaData, Table, inspect, text

from server.core import Base
from server.core.migrations import BASELINE_REVISION, alembic_config, run_migrations


def _head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def test_revisions_form_a_single_line():
    """Two branches that each add a revision leave two heads, and the app can't upgrade to both."""
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


def _version(engine) -> str | None:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


# urls.og_fetched_at, unwritten since 8.7, is no longer mapped, and the migration that drops it
# ships in the release after: the previous release's tasks still select it, and would fail
# mid-rollout (users.api_key went the same way, 0014). Until then the drift check ignores exactly
# that column; test_the_pending_drop_is_still_pending fails once it's gone, and both go.
_PENDING_DROP = {("column", "urls", "og_fetched_at")}


def _not_a_pending_drop(obj, name, type_, reflected, compare_to) -> bool:
    table = getattr(getattr(obj, "table", None), "name", None)
    return (type_, table, name) not in _PENDING_DROP


def _drift(engine) -> list:
    """What `alembic revision --autogenerate` would still write: models vs. database."""
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"include_object": _not_a_pending_drop})
        return compare_metadata(context, Base.metadata)


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


def _what(diff) -> tuple:
    if diff[0] == "remove_column":
        return ("column", diff[2], diff[3].name)
    return diff


def test_the_pending_drop_is_still_pending(pg_engine):
    """The drift check ignores urls.og_fetched_at until its migration drops it, and nothing
    else. When this fails because it's gone: delete `_PENDING_DROP` and this test."""
    run_migrations(pg_engine)

    assert "og_fetched_at" in {column["name"] for column in inspect(pg_engine).get_columns("urls")}
    with pg_engine.connect() as conn:
        unfiltered = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert {_what(diff) for diff in unfiltered} == _PENDING_DROP


def test_the_drift_check_ignores_nothing_else():
    """Exactly urls.og_fetched_at: not a column of that name elsewhere, nor another of urls'
    columns or the table."""
    legacy = Table("urls", MetaData(), Column("og_fetched_at", DateTime(timezone=True)))
    elsewhere = Table("visitors", MetaData(), Column("og_fetched_at", DateTime(timezone=True)))
    urls = Base.metadata.tables["urls"]

    assert not _not_a_pending_drop(legacy.c.og_fetched_at, "og_fetched_at", "column", True, None)
    assert _not_a_pending_drop(elsewhere.c.og_fetched_at, "og_fetched_at", "column", True, None)
    assert _not_a_pending_drop(urls.c.page_fetched_at, "page_fetched_at", "column", False, None)
    assert _not_a_pending_drop(urls, "urls", "table", False, None)
