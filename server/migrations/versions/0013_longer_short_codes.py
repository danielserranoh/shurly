"""Short codes up to 64 characters (Phase 8.4).

`urls.short_code` and `visits.short_code` go from VARCHAR(20) to VARCHAR(64)
(MAX_SHORT_CODE_LENGTH): Shlink's links on go.griddo.io run to 44 characters, and are
out there already. Widening a VARCHAR only changes PostgreSQL's catalog, with no table
rewrite, and the indexes on the columns stay valid. The previous release, which reads
and writes codes of up to 20, keeps working during the rollout.

The downgrade fails while a code longer than 20 is kept: PostgreSQL won't cut one.

Not here: dropping users.api_key, which the model no longer maps. That's 0014's.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-01 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("urls", "visits")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "short_code",
            existing_type=sa.String(length=20),
            type_=sa.String(length=64),
            existing_nullable=False,
        )


def downgrade() -> None:
    for table in _TABLES:
        op.alter_column(
            table,
            "short_code",
            existing_type=sa.String(length=64),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
