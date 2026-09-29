"""A link's last click is a click (Phase 3.16).

`urls.last_click_at` moved on every visit the redirect logged, bots included, and the Shlink
import counted Shlink's potential bots. The app now sets it on a click only: not a bot's
visit, not an email open. This sets it to each link's latest click, or NULL without one.

Data only, in two statements whatever the number of links: the previous release keeps working
during the rollout, and may set a bot's time again until it ends. Not here: dropping
users.api_key, which the model no longer maps. That's 0011's.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A click as `_exclude_bots` counts one (server/app/analytics.py): not a pixel hit, not a
    # bot's. `visited_at` is naive UTC and `last_click_at` a timestamptz: read the former as
    # UTC, whatever the session's time zone. A raw UPDATE leaves `updated_at` as it was.
    op.execute(
        """
        UPDATE urls SET last_click_at = clicks.latest AT TIME ZONE 'UTC'
        FROM (
            SELECT visits.url_id, max(visits.visited_at) AS latest
            FROM visits
            WHERE visits.is_pixel = false AND visits.is_bot = false
            GROUP BY visits.url_id
        ) AS clicks
        WHERE urls.id = clicks.url_id
        """
    )
    op.execute(
        """
        UPDATE urls SET last_click_at = NULL
        WHERE last_click_at IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM visits
              WHERE visits.url_id = urls.id AND visits.is_pixel = false AND visits.is_bot = false
          )
        """
    )


def downgrade() -> None:
    # Nothing to undo: the times it replaced were bots' and shouldn't come back.
    pass
