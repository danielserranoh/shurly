"""
People by name (Phase 3.12): a user's first and last name, from their profile.

Wherever people are listed (members, removed people, "Created by"), responses keep the email
and add these. Load `User.profile` with the list (selectinload), or each name costs a query.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.core.models import User


def names(user: User | None) -> tuple[str | None, str | None]:
    """(first, last) from the profile; (None, None) without a user or a profile."""
    profile = user.profile if user is not None else None
    if profile is None:
        return None, None
    return profile.first_name, profile.last_name
