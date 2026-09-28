"""API keys kept as a hash and a prefix, never as themselves (Phase 6.3).

Adds users.api_key_hash (SHA-256 hex, unique) and users.api_key_prefix, moves every
existing key into them and empties users.api_key. The column itself goes in a later
release: the previous release still selects it during the rollout.

That release looks keys up in the plaintext column, which this empties, so API keys
answer 401 until the rollout ends (decided 2026-09-28: no users yet). Existing keys
work again right after, from their hash.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-28 23:40:00.000000

"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# As the app keeps them (server/core/models/user.py): SHA-256, and the first 12 characters.
_PREFIX_LENGTH = 12


def upgrade() -> None:
    op.add_column("users", sa.Column("api_key_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "users", sa.Column("api_key_prefix", sa.String(length=_PREFIX_LENGTH), nullable=True)
    )
    op.create_index(op.f("ix_users_api_key_hash"), "users", ["api_key_hash"], unique=True)

    conn = op.get_bind()
    keys = conn.execute(sa.text("SELECT id, api_key FROM users WHERE api_key IS NOT NULL"))
    for user_id, key in keys.fetchall():
        conn.execute(
            sa.text(
                "UPDATE users SET api_key_hash = :hash, api_key_prefix = :prefix, api_key = NULL"
                " WHERE id = :id"
            ),
            {
                "hash": hashlib.sha256(key.encode()).hexdigest(),
                "prefix": key[:_PREFIX_LENGTH],
                "id": user_id,
            },
        )


def downgrade() -> None:
    # A hash can't give the key back: after a downgrade, people generate a new one.
    op.drop_index(op.f("ix_users_api_key_hash"), table_name="users")
    op.drop_column("users", "api_key_prefix")
    op.drop_column("users", "api_key_hash")
