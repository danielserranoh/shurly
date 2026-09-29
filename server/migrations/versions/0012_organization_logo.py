"""The organization's logo (Phase 3.14.4).

Adds organizations.logo (a WebP within 512×512), its content type and when it was
uploaded. New nullable columns only: the previous release never selects them.

Not here: dropping users.api_key, which the model no longer maps. That's 0013's.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("logo", sa.LargeBinary(), nullable=True))
    op.add_column(
        "organizations", sa.Column("logo_content_type", sa.String(length=32), nullable=True)
    )
    op.add_column("organizations", sa.Column("logo_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "logo_updated_at")
    op.drop_column("organizations", "logo_content_type")
    op.drop_column("organizations", "logo")
