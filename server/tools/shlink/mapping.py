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


def map_condition(condition: dict) -> tuple[dict | None, str | None]:
    """
    A Shlink redirect-rule condition as Shurly's (server/utils/redirect_rules.py), and a note
    when Shurly's matches more than Shlink's did. None when Shurly has no equivalent: the
    import then leaves the whole rule out, since dropping one condition would widen it.
    """
    kind = condition.get("type")
    key, value = condition.get("matchKey"), condition.get("matchValue")
    shurly = CONDITION_TYPES.get(kind)
    if shurly is None:
        return None, f"{kind} has no equivalent in Shurly"
    if kind == "language":
        # Shurly compares the primary subtag only: en-US matches every en.
        primary = str(value or "").replace("_", "-").split("-")[0].lower()
        note = (
            None
            if primary == str(value or "").lower()
            else f"language {value} matches every {primary}"
        )
        return {"type": "language", "value": primary}, note
    if kind == "query-param":
        return {"type": "query_param", "param": key, "value": value}, None
    if kind == "any-value-query-param":
        return {"type": "query_param", "param": key}, None
    if kind == "valueless-query-param":
        return {
            "type": "query_param",
            "param": key,
        }, f"valueless-query-param {key} also matches ?{key}=…"
    return {"type": shurly, "value": value}, None
