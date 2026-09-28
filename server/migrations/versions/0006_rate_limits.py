"""Rate-limit counters (Phase 6.3).

One row per key, shared by every task. A new table only.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-28 22:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index(
        op.f("ix_rate_limits_window_start"), "rate_limits", ["window_start"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rate_limits_window_start"), table_name="rate_limits")
    op.drop_table("rate_limits")
