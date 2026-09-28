"""
Phase 8.4 — the country a visit comes from, for the geo view: an ISO 3166-1 alpha-2 code
from DB-IP's IP to Country Lite database (CC BY 4.0, https://db-ip.com), which the image
build fetches (scripts/fetch_geoip.py).

In process, from a memory-mapped file opened once: no network call on the redirect path.
The caller looks up the address it stores, anonymized when ANONYMIZE_REMOTE_ADDR is on, so
the lookup never sees more than what's kept (DEPLOYMENT.md § GDPR posture). A missing or
unreadable database means no country, logged once at startup (`geo.database_missing`),
never a failed request.
"""

import threading

import maxminddb

from server.core.config import settings
from server.utils.event_log import log_event

_lock = threading.Lock()
_reader: maxminddb.Reader | None = None
_opened = False


def open_database() -> maxminddb.Reader | None:
    """The database GEOIP_DATABASE names, opened on first use; None without one."""
    global _reader, _opened
    if not _opened:
        with _lock:
            if not _opened:
                path = settings.geoip_database
                if path:
                    try:
                        _reader = maxminddb.open_database(path, maxminddb.MODE_MMAP)
                    except (OSError, ValueError, maxminddb.InvalidDatabaseError) as error:
                        log_event("geo.database_missing", path=path, error=type(error).__name__)
                _opened = True
    return _reader


def reset() -> None:
    """Close the database, to open GEOIP_DATABASE again on next use (tests)."""
    global _reader, _opened
    with _lock:
        if _reader is not None:
            _reader.close()
        _reader, _opened = None, False


def country_of(address: str | None) -> str | None:
    """`address`'s ISO country code, or None: no database, no record, or not an address."""
    reader = open_database()
    if reader is None or not address:
        return None
    try:
        record = reader.get(address)
    except (ValueError, maxminddb.InvalidDatabaseError):
        return None
    code = ((record or {}).get("country") or {}).get("iso_code")
    return code if isinstance(code, str) else None
