"""
Phase 3.14.1 — schema migrations with Alembic, run at startup.

`create_all()` only creates missing tables; it never adds a column to one that
exists. So Alembic owns the schema now (revisions in `server/migrations/`).

Every task runs this when it boots, and ECS starts them side by side. A
PostgreSQL advisory lock, held for the migration's transaction, lets the first
task migrate while the others wait and then find nothing to do.

A database built by `create_all()` before Alembic (production) has the
baseline's tables but no `alembic_version`: it is stamped at the baseline, which
matches it, and then upgraded like any other.

During a rolling deploy the old tasks keep serving on the new schema, so a
revision must work for the previous release too: add columns and tables in one
release, drop or rename in a later one.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

BASELINE_REVISION = "0001"

# Any fixed number: every task asks PostgreSQL for the same advisory lock.
_MIGRATION_LOCK = 31401

_SCRIPT_LOCATION = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config() -> Config:
    """Alembic's configuration without alembic.ini, which isn't in the image."""
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    return config


def run_migrations(engine: Engine) -> None:
    """Bring the database to the latest revision, in one transaction."""
    config = alembic_config()
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Released when this transaction ends.
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK})
        config.attributes["connection"] = connection
        tables = inspect(connection).get_table_names()
        if "alembic_version" not in tables and "users" in tables:
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
