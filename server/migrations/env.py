"""
Alembic environment (Phase 3.14.1).

Two ways in:
- The app, at startup: `server/core/migrations.py` hands over an open connection
  (inside the transaction that holds the migration lock) in
  `config.attributes["connection"]`.
- The CLI (`uv run alembic …`, e.g. `revision --autogenerate`): connects with the
  app's own settings (the DB_* variables), so there's no URL in alembic.ini.
"""

from logging.config import fileConfig

from alembic import context

import server.core.models  # noqa: F401 — registers every model on Base.metadata
from server.core import Base, engine
from server.core.config import settings

config = context.config

# Only when run from the CLI with alembic.ini; the app keeps its own logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit the SQL instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return

    # The app's engine: same settings, including RDS's `sslmode`.
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
