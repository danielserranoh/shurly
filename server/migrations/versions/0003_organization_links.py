"""Links and campaigns belong to an organization (Phase 3.14.3).

`organization_id` NULL means personal: only the creator sees it. Everything made
before organizations existed becomes the organization's, the default from now on.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-27 20:56:38.618373

"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

from server.core.config import settings

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("campaigns", "urls"):
        op.add_column(table, sa.Column("organization_id", sa.UUID(), nullable=True))
        op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
        op.create_foreign_key(
            f"{table}_organization_id_fkey", table, "organizations", ["organization_id"], ["id"]
        )

    # The app makes the organization at startup, after migrating: when 0002 and 0003
    # run in the same boot there is none yet. Make it here, as the app would.
    conn = op.get_bind()
    has_rows = conn.scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM urls UNION ALL SELECT 1 FROM campaigns)")
    )
    if has_rows and not conn.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM organizations)")):
        organizations = sa.table(
            "organizations",
            sa.column("id", sa.UUID()),
            sa.column("name", sa.String()),
            sa.column("google_domain", sa.String()),
            sa.column("created_at", sa.DateTime()),
        )
        op.bulk_insert(
            organizations,
            [
                {
                    "id": uuid.uuid4(),
                    "name": settings.organization_name,
                    "google_domain": settings.organization_domain or None,
                    "created_at": datetime.utcnow(),
                }
            ],
        )

    for table in ("campaigns", "urls"):
        op.execute(
            f"UPDATE {table} SET organization_id ="
            " (SELECT id FROM organizations ORDER BY created_at LIMIT 1)"
            " WHERE organization_id IS NULL"
        )


def downgrade() -> None:
    for table in ("urls", "campaigns"):
        op.drop_constraint(f"{table}_organization_id_fkey", table, type_="foreignkey")
        op.drop_index(op.f(f"ix_{table}_organization_id"), table_name=table)
        op.drop_column(table, "organization_id")
