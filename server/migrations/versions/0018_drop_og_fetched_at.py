"""Drop urls.og_fetched_at, unused since the page previews (Phase 8.7, migration 0015).

Before 8.7 it said when a link's og_* values had been copied from its page. 8.7 moved the
page's preview to the `page_*` columns, with `page_fetched_at`, and stopped writing it; 0015
kept it because the release before 8.7 still wrote it, and the one-off backfill read it to
tell the og_* values copied from the page from the ones a person typed. That backfill has
run in production, and no release since 8.7 writes the column or reads what it holds.

8.7 and later still map it, though, and the ORM names every mapped column in its SELECTs: a
task of a release that maps it, still serving during the rollout, fails every link query
once the column is gone (users.api_key's drop, 0014, waited a release for the same reason).
The cleanup sweep stopped mapping it, and that release is in production (2026-10-18, #248),
so the previous release's tasks no longer name it. It has no index.

The downgrade adds the column back as it was, TIMESTAMP WITH TIME ZONE, nullable, but empty:
the times it held are gone, and nothing has read them since 8.7.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0018"
down_revision: str | Sequence[str] | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("urls", "og_fetched_at")


def downgrade() -> None:
    op.add_column("urls", sa.Column("og_fetched_at", sa.DateTime(timezone=True), nullable=True))
