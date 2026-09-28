"""Sign in with Google: identities, sign-ins in progress, one-time codes (Phase 3.13).

- `user_identities`: an account at Google, recognised by its `sub`.
- `google_auth_states` and `login_codes`: the sign-in flow's short-lived secrets,
  single use and stored hashed (the PKCE verifier excepted).
- `users.password_hash` may be NULL: an account made through Google has no password.
- `users.sessions_valid_from`: JWTs issued in an earlier second are refused.

All of it works for the release still serving during the rollout. That release
never writes a NULL password; it would fail (500) a password login for an account
whose password the new release has just cleared, until the rollout ends.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28 16:40:00.000000

"""

import secrets
from collections.abc import Sequence

import bcrypt
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "subject"),
    )
    op.create_index(
        op.f("ix_user_identities_user_id"), "user_identities", ["user_id"], unique=False
    )
    op.create_table(
        "google_auth_states",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("state_hash"),
    )
    op.create_table(
        "login_codes",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("code_hash"),
    )
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)
    op.add_column("users", sa.Column("sessions_valid_from", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # The previous release needs a password on every account: accounts without one
    # get a random password nobody knows, so they still can't sign in with one.
    unusable = bcrypt.hashpw(secrets.token_hex(32).encode(), bcrypt.gensalt()).decode()
    op.execute(
        sa.text(
            "UPDATE users SET password_hash = :unusable WHERE password_hash IS NULL"
        ).bindparams(unusable=unusable)
    )
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("users", "sessions_valid_from")
    op.drop_table("login_codes")
    op.drop_table("google_auth_states")
    op.drop_index(op.f("ix_user_identities_user_id"), table_name="user_identities")
    op.drop_table("user_identities")
