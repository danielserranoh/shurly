"""
Phase 3.12 — what a profile accepts. The API's schema (server/schemas/profile.py) and the
names Google gives at sign-in (server/utils/google_sign_in.py) go through the same rules.

Each `clean_*` takes what was sent: a string comes back cleaned, or None when it's blank;
one the field can't take raises ValueError, with the message the API answers. Anything
else passes through untouched, for the schema's type check.
"""

import unicodedata

from server.utils.timezones import countries, preferred_timezone

NAME_MAX_LENGTH = 100
# A name is one line: no control characters, no line or paragraph separators.
_NOT_IN_A_NAME = {"Cc", "Zl", "Zp"}


def clean_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    value = value.strip()
    if not value:
        return None
    if any(unicodedata.category(char) in _NOT_IN_A_NAME for char in value):
        raise ValueError("A name can't have line breaks or control characters")
    return value


def clean_country(value: object) -> object:
    if not isinstance(value, str):
        return value
    code = value.strip().upper()
    if not code:
        return None
    if code not in countries():
        raise ValueError("Not a country code: use ISO 3166-1 alpha-2, like ES")
    return code


def clean_timezone(value: object) -> object:
    if not isinstance(value, str):
        return value
    if not value.strip():
        return None
    name = preferred_timezone(value)
    if name is None:
        raise ValueError("Not a time zone: use an IANA name, like Europe/Madrid")
    return name
