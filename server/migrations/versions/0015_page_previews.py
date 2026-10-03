"""Previews from the page (Phase 8.7).

A link's social preview comes in two layers. `og_title`, `og_description` and `og_image_url`
hold only what a person typed; the new `page_*` columns cache what the destination declares
(its Open Graph title, description and image, and its icon), with `page_fetched_at`, the time
of the fetch they come from. Each field's effective value is the override, else the page's.

All nullable and without a default, so PostgreSQL only changes its catalog, whatever the
table's size, and the previous release, which doesn't map them, keeps working during the
rollout. Nothing is fetched here: the one-off backfill fills them after the release
(`python -m server.tools.previews backfill`, DEPLOYMENT.md), and separates the og_* values
it finds were copied from the page from the ones a person typed.

`urls.og_fetched_at` stays, unused by this release: the previous one still writes it, and the
backfill reads it (set, the og_* values were most likely copied from the page). A later
migration drops it, once the release before this one is gone.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("urls", sa.Column("page_og_title", sa.String(length=255), nullable=True))
    op.add_column("urls", sa.Column("page_og_description", sa.Text(), nullable=True))
    op.add_column("urls", sa.Column("page_og_image_url", sa.Text(), nullable=True))
    op.add_column("urls", sa.Column("page_favicon_url", sa.Text(), nullable=True))
    op.add_column("urls", sa.Column("page_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("urls", "page_fetched_at")
    op.drop_column("urls", "page_favicon_url")
    op.drop_column("urls", "page_og_image_url")
    op.drop_column("urls", "page_og_description")
    op.drop_column("urls", "page_og_title")
