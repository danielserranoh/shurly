"""Baseline: the schema `create_all()` built before Alembic (Phase 3.14.1).

A database created that way (production) has these tables but no `alembic_version`;
`server/core/migrations.py` stamps it at this revision instead of running it.

Revision ID: 0001
Revises:
Create Date: 2026-09-27 20:20:09.768107

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_domains_hostname"), "domains", ["hostname"], unique=True)
    op.create_index(op.f("ix_domains_is_default"), "domains", ["is_default"], unique=False)
    op.create_table(
        "orphan_visits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "type",
            sa.Enum("BASE_URL", "INVALID_SHORT_URL", "REGULAR_404", name="orphanvisittype"),
            nullable=False,
        ),
        sa.Column("attempted_path", sa.String(length=2048), nullable=False),
        sa.Column("ip", sa.String(length=50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("referer", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_orphan_visits_created_at"), "orphan_visits", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_orphan_visits_type"), "orphan_visits", ["type"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("api_key", sa.String(length=64), nullable=True),
        sa.Column(
            "api_key_scope",
            sa.Enum(
                "FULL_ACCESS", "READ_ONLY", "CREATE_ONLY", "DOMAIN_SPECIFIC", name="apikeyscope"
            ),
            nullable=False,
        ),
        sa.Column("api_key_constraints", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_api_key"), "users", ["api_key"], unique=True)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_table(
        "campaigns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("csv_columns", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("display_name", sa.String(length=30), nullable=False),
        sa.Column("color", sa.String(length=20), nullable=False),
        sa.Column("is_predefined", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.CheckConstraint("name = LOWER(name)", name="name_lowercase_check"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "campaign_tags",
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "tag_id"),
    )
    op.create_table(
        "urls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("short_code", sa.String(length=20), nullable=False),
        sa.Column("domain_id", sa.UUID(), nullable=True),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column(
            "url_type", sa.Enum("STANDARD", "CUSTOM", "CAMPAIGN", name="urltype"), nullable=False
        ),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("campaign_id", sa.UUID(), nullable=True),
        sa.Column("user_data", sa.JSON(), nullable=True),
        sa.Column("forward_parameters", sa.Boolean(), nullable=False),
        sa.Column("og_title", sa.String(length=255), nullable=True),
        sa.Column("og_description", sa.Text(), nullable=True),
        sa.Column("og_image_url", sa.Text(), nullable=True),
        sa.Column("og_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_click_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_visits", sa.Integer(), nullable=True),
        sa.Column("crawlable", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["domain_id"],
            ["domains.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("domain_id", "short_code", name="uq_urls_domain_code"),
    )
    op.create_index(op.f("ix_urls_domain_id"), "urls", ["domain_id"], unique=False)
    op.create_index(op.f("ix_urls_short_code"), "urls", ["short_code"], unique=False)
    op.create_table(
        "redirect_rules",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("url_id", sa.UUID(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["url_id"],
            ["urls.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_redirect_rules_priority"), "redirect_rules", ["priority"], unique=False
    )
    op.create_index(op.f("ix_redirect_rules_url_id"), "redirect_rules", ["url_id"], unique=False)
    op.create_table(
        "url_tags",
        sa.Column("url_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["url_id"], ["urls.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("url_id", "tag_id"),
    )
    op.create_table(
        "visits",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("url_id", sa.UUID(), nullable=False),
        sa.Column("short_code", sa.String(length=20), nullable=False),
        sa.Column("ip", sa.String(length=50), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("referer", sa.Text(), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False),
        sa.Column("is_pixel", sa.Boolean(), nullable=False),
        sa.Column("visited_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["url_id"],
            ["urls.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_visits_is_bot"), "visits", ["is_bot"], unique=False)
    op.create_index(op.f("ix_visits_is_pixel"), "visits", ["is_pixel"], unique=False)
    op.create_index(op.f("ix_visits_short_code"), "visits", ["short_code"], unique=False)
    op.create_index(op.f("ix_visits_url_id"), "visits", ["url_id"], unique=False)
    op.create_index(op.f("ix_visits_visited_at"), "visits", ["visited_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_visits_visited_at"), table_name="visits")
    op.drop_index(op.f("ix_visits_url_id"), table_name="visits")
    op.drop_index(op.f("ix_visits_short_code"), table_name="visits")
    op.drop_index(op.f("ix_visits_is_pixel"), table_name="visits")
    op.drop_index(op.f("ix_visits_is_bot"), table_name="visits")
    op.drop_table("visits")
    op.drop_table("url_tags")
    op.drop_index(op.f("ix_redirect_rules_url_id"), table_name="redirect_rules")
    op.drop_index(op.f("ix_redirect_rules_priority"), table_name="redirect_rules")
    op.drop_table("redirect_rules")
    op.drop_index(op.f("ix_urls_short_code"), table_name="urls")
    op.drop_index(op.f("ix_urls_domain_id"), table_name="urls")
    op.drop_table("urls")
    op.drop_table("campaign_tags")
    op.drop_table("tags")
    op.drop_table("campaigns")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_api_key"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_orphan_visits_type"), table_name="orphan_visits")
    op.drop_index(op.f("ix_orphan_visits_created_at"), table_name="orphan_visits")
    op.drop_table("orphan_visits")
    op.drop_index(op.f("ix_domains_is_default"), table_name="domains")
    op.drop_index(op.f("ix_domains_hostname"), table_name="domains")
    op.drop_table("domains")
    # drop_table leaves PostgreSQL enum types behind; drop them too.
    for enum_type in ("urltype", "apikeyscope", "orphanvisittype"):
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
