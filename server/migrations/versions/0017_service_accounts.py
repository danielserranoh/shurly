"""Service accounts (Phase 10.1).

`users.kind` ('person' for every existing row, by its server default) and a service account's
display name, description and person responsible; `service_tokens`, a service account's tokens,
kept as hashes; and on `urls`, the service account and the token that created a link.

Add-only: the previous release doesn't map any of it and keeps working during the rollout. The
server default fills `kind` for the accounts it makes.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | Sequence[str] | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("kind", sa.String(length=16), server_default="person", nullable=False),
    )
    op.add_column("users", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("responsible_user_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "users_responsible_user_id_fkey",
        "users",
        "users",
        ["responsible_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "service_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("service_account_id", sa.UUID(), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("replaced_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_by_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["service_account_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_service_tokens_service_account_id"),
        "service_tokens",
        ["service_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_service_tokens_token_hash"), "service_tokens", ["token_hash"], unique=True
    )

    op.add_column("urls", sa.Column("via_service_account_id", sa.UUID(), nullable=True))
    op.add_column("urls", sa.Column("via_token_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "urls_via_service_account_id_fkey", "urls", "users", ["via_service_account_id"], ["id"]
    )
    op.create_foreign_key(
        "urls_via_token_id_fkey", "urls", "service_tokens", ["via_token_id"], ["id"]
    )
    op.create_index(
        op.f("ix_urls_via_service_account_id"), "urls", ["via_service_account_id"], unique=False
    )
    op.create_index(op.f("ix_urls_via_token_id"), "urls", ["via_token_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_urls_via_token_id"), table_name="urls")
    op.drop_index(op.f("ix_urls_via_service_account_id"), table_name="urls")
    op.drop_constraint("urls_via_token_id_fkey", "urls", type_="foreignkey")
    op.drop_constraint("urls_via_service_account_id_fkey", "urls", type_="foreignkey")
    op.drop_column("urls", "via_token_id")
    op.drop_column("urls", "via_service_account_id")
    op.drop_index(op.f("ix_service_tokens_token_hash"), table_name="service_tokens")
    op.drop_index(op.f("ix_service_tokens_service_account_id"), table_name="service_tokens")
    op.drop_table("service_tokens")
    op.drop_constraint("users_responsible_user_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "responsible_user_id")
    op.drop_column("users", "description")
    op.drop_column("users", "display_name")
    op.drop_column("users", "kind")
