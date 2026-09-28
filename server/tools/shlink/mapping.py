"""Phase 8.4 — how Shlink's concepts map onto Shurly's. The review flags what doesn't."""

# Shlink's redirect-rule conditions (SetShortUrlRedirectRule in its API spec) → Shurly's
# (server/utils/redirect_rules.py). None: Shurly has no equivalent, so a rule using it
# can't be migrated as it is.
CONDITION_TYPES: dict[str, str | None] = {
    "device": "device",
    "language": "language",
    "browser": "browser",
    "query-param": "query_param",
    "any-value-query-param": "query_param",
    "valueless-query-param": "query_param",
    "before-date": "before_date",
    "after-date": "after_date",
    "ip-address": None,
    "geolocation-country-code": None,
    "geolocation-city-name": None,
}
