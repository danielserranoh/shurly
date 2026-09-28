"""The MCP OAuth proxy's state (Phase 5.8).

fastmcp's OAuth proxy keeps client registrations, sign-ins in progress,
authorization codes and Google's tokens in a key-value store. This is its table,
so every task shares it and a deploy doesn't lose it. A new table only.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-28 19:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_store",
        sa.Column("collection", sa.String(length=128), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("collection", "key"),
    )
    op.create_index(
        op.f("ix_mcp_oauth_store_expires_at"), "mcp_oauth_store", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mcp_oauth_store_expires_at"), table_name="mcp_oauth_store")
    op.drop_table("mcp_oauth_store")
