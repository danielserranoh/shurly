"""The waitlist (Phase 9.1).

People outside Griddo who'd like Shurly: one row per email, with what they typed and when they
agreed to be contacted. Never an IP. A new table only, so the previous release, which doesn't
map it, keeps working during the rollout.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("company_size", sa.String(length=16), nullable=True),
        sa.Column("role", sa.String(length=120), nullable=True),
        sa.Column("use_case", sa.String(length=1000), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("consent_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(
        op.f("ix_waitlist_entries_created_at"), "waitlist_entries", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_waitlist_entries_created_at"), table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
