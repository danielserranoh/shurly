"""The avatar, in the profile (Phase 3.12).

Adds user_profiles.avatar (the 512×512 WebP), its content type and when it was
uploaded. New nullable columns only: the previous release never selects them.

Not here: dropping users.api_key, which the model no longer maps. That's 0014's.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28 20:07:33.452877

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("avatar", sa.LargeBinary(), nullable=True))
    op.add_column(
        "user_profiles", sa.Column("avatar_content_type", sa.String(length=32), nullable=True)
    )
    op.add_column("user_profiles", sa.Column("avatar_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "avatar_updated_at")
    op.drop_column("user_profiles", "avatar_content_type")
    op.drop_column("user_profiles", "avatar")
