"""A visit's city (Phase 8.4).

`visits.city`: its English name, from MaxMind's GeoLite2 City, looked up from the stored
address. Nullable and without a default, so PostgreSQL only changes its catalog, whatever the
table's size, and the previous release, which doesn't map it, keeps working during the
rollout. Earlier visits stay NULL until the one-off backfill fills them
(`python -m server.tools.backfill_places`).

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("visits", sa.Column("city", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("visits", "city")
