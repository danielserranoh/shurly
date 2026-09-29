"""
Phase 6.1 — when the end-to-end API (app.py) may start: on purpose, and on a
local database only. It signs anyone in through a fake Google, and the first
account becomes the organization's owner, so it must never meet real data.
"""

import os

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def refuse_unless_local() -> None:
    """Exit unless E2E=1 and DB_HOST names this machine (set, not a default from .env)."""
    if os.environ.get("E2E") != "1":
        raise SystemExit(
            "tests/e2e/app.py signs anyone in through a fake Google: it starts only with "
            "E2E=1, for the end-to-end tests (see docs/TESTING.md)."
        )
    host = os.environ.get("DB_HOST", "")
    if host.strip().lower() not in LOCAL_HOSTS:
        raise SystemExit(
            "tests/e2e/app.py runs only on a local, throwaway database: set DB_HOST to "
            f"localhost, 127.0.0.1 or ::1 (it is {host!r})."
        )
