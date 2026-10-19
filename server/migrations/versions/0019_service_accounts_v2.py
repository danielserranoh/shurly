"""Service accounts v2 (Phase 10.2): token scopes and allowed IP ranges, and the audit table.

On `service_tokens`, `scopes`, what a token may do, and `allowed_ip_ranges`, the CIDR ranges it
may be used from (NULL, any address); and `audit_events`, what service accounts do, kept 2
years.

Add-only: the previous release doesn't map any of it and keeps working during the rollout. The
tokens it makes, and the ones already in use (Propuestas'), get every scope from the server
default, so nothing they do now is refused once the scopes are enforced.

The scope list is written out here, not imported: a migration keeps the values it had when it
ran. It matches `SERVICE_SCOPES` in server/core/models/service_token.py.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVERY_SCOPE = (
    '["urls:read", "urls:write", "urls:delete", "tags:write", "analytics:read", "act_on_behalf"]'
)


def upgrade() -> None:
    op.add_column(
        "service_tokens",
        sa.Column("scopes", sa.JSON(), server_default=sa.text(f"'{EVERY_SCOPE}'"), nullable=False),
    )
    op.add_column("service_tokens", sa.Column("allowed_ip_ranges", sa.JSON(), nullable=True))

    op.create_table(
        "audit_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("service_account_id", sa.UUID(), nullable=False),
        sa.Column("token_id", sa.UUID(), nullable=True),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("on_behalf_of_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_events_organization_id_at",
        "audit_events",
        ["organization_id", "at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_audit_events_service_account_id"),
        "audit_events",
        ["service_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_events_service_account_id"), table_name="audit_events")
    op.drop_index("ix_audit_events_organization_id_at", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_column("service_tokens", "allowed_ip_ranges")
    op.drop_column("service_tokens", "scopes")
