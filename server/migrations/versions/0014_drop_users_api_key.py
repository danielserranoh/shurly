"""Drop users.api_key, the plaintext API key column (Phase 6.3, shipped in 8.5).

0007 moved every key to its hash (users.api_key_hash) and emptied the column, and the
release after stopped mapping it: the ORM names every mapped column in its SELECTs and
INSERTs, so a task of the previous release, still serving during the rollout, never
selects it. That release is in production (0013 shipped on 2026-10-02), so the column and
its unique index, ix_users_api_key (the baseline's, and create_all()'s before it), go.

The downgrade adds the column back as it was, VARCHAR(64), nullable, with its unique
index, but empty: the keys it held are gone (0007 had moved them to their hash already),
and a hash can't give a key back.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-02 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL drops a column's indexes with it; named here so the drop says what goes.
    op.drop_index(op.f("ix_users_api_key"), table_name="users", if_exists=True)
    op.drop_column("users", "api_key")


def downgrade() -> None:
    op.add_column("users", sa.Column("api_key", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_users_api_key"), "users", ["api_key"], unique=True)
