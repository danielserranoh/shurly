"""
Phase 8.4 — where a visit comes from, for the geo view: its country, an ISO 3166-1 alpha-2
code, and its city, by its English name. From MaxMind's GeoLite2 City (GEOIP_DATABASE), or
DB-IP's IP to Country Lite (CC BY 4.0, https://db-ip.com), countries only, when it isn't there
(GEOIP_FALLBACK_DATABASE). The image build fetches both (scripts/fetch_geoip.py).

In process, from a memory-mapped file opened once: no network call on the redirect path.
The caller looks up the address it stores, anonymized when ANONYMIZE_REMOTE_ADDR is on, so
the lookup never sees more than what's kept (DEPLOYMENT.md § GDPR posture). Neither database
means no country, logged once at startup (`geo.database_missing`), never a failed request.

What opened is logged too (`geo.database_opened`), with its age. MaxMind's licence wants a
GeoLite2 copy replaced within 30 days of an update: past 25, `geo.database_stale` says so.
"""

import threading
import time
from typing import NamedTuple

import maxminddb

from server.core.config import settings
from server.utils.event_log import log_event

STALE_AFTER_DAYS = 25  # MaxMind's EULA gives 30 from an update; the image is rebuilt weekly

_lock = threading.Lock()
_reader: maxminddb.Reader | None = None
_opened = False


def open_database() -> maxminddb.Reader | None:
    """GEOIP_DATABASE, else GEOIP_FALLBACK_DATABASE, opened on first use; None without either.
    An empty GEOIP_DATABASE turns lookups off."""
    global _reader, _opened
    if not _opened:
        with _lock:
            if not _opened:
                if settings.geoip_database:
                    _reader = _first_that_opens(
                        settings.geoip_database, settings.geoip_fallback_database
                    )
                _opened = True
    return _reader


def _first_that_opens(primary: str, fallback: str) -> maxminddb.Reader | None:
    errors: dict[str, str] = {}
    for path in (primary, fallback):
        if not path:
            continue
        try:
            reader = maxminddb.open_database(path, maxminddb.MODE_MMAP)
        except (OSError, ValueError, maxminddb.InvalidDatabaseError) as error:
            errors[path] = type(error).__name__
            continue
        # Opened the fallback: say which file didn't open, and why.
        failed = {"primary": primary, "primary_error": errors[primary]} if errors else {}
        _log_opened(path, reader.metadata(), **failed)
        return reader
    log_event(
        "geo.database_missing",
        path=primary,
        error=errors.get(primary),
        fallback=fallback or None,
        fallback_error=errors.get(fallback) if fallback else None,
    )
    return None


def _log_opened(path: str, metadata, **fallback) -> None:
    age_days = round((_now() - metadata.build_epoch) / 86400, 1)
    log_event(
        "geo.database_opened",
        path=path,
        database_type=metadata.database_type,
        built=time.strftime("%Y-%m-%d", time.gmtime(metadata.build_epoch)),
        age_days=age_days,
        **fallback,
    )
    if metadata.database_type.startswith("GeoLite2") and age_days > STALE_AFTER_DAYS:
        log_event(
            "geo.database_stale",
            path=path,
            age_days=age_days,
            warning="MaxMind's licence wants it replaced within 30 days of an update: "
            "the weekly redeploy (deploy-backend.yml) hasn't run",
        )


def _now() -> float:
    return time.time()


def reset() -> None:
    """Close the database, to open GEOIP_DATABASE again on next use (tests)."""
    global _reader, _opened
    with _lock:
        if _reader is not None:
            _reader.close()
        _reader, _opened = None, False


class Place(NamedTuple):
    country: str | None  # an ISO code
    city: str | None  # its English name


NOWHERE = Place(None, None)


def place_of(address: str | None) -> Place:
    """`address`'s country and city, each None when unknown: no database, no record, not an
    address, or no city in the record (DB-IP's has none; GeoLite2 lacks many)."""
    reader = open_database()
    if reader is None or not address:
        return NOWHERE
    try:
        record = reader.get(address)
    except (ValueError, maxminddb.InvalidDatabaseError):
        return NOWHERE
    record = record or {}
    code = (record.get("country") or {}).get("iso_code")
    city = ((record.get("city") or {}).get("names") or {}).get("en")
    return Place(
        code if isinstance(code, str) else None,
        (city.strip() or None) if isinstance(city, str) else None,
    )


def country_of(address: str | None) -> str | None:
    """`address`'s ISO country code, or None: no database, no record, or not an address."""
    return place_of(address).country
