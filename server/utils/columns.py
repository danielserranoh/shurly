"""
Phase 6.3 — values from outside a request's schema, cut to their column.

A request field is checked against its column by its schema (max_length, a 422).
A value from elsewhere, a fetched page's title or an address from
X-Forwarded-For, can be any length, and PostgreSQL refuses a row whose value is
longer than its VARCHAR: a 500 on a link or a redirect because of someone else's
page or header. Those values are cut to fit instead.
"""


def fit(value: str | None, column) -> str | None:
    """`value`, at most as long as `column` (a String(n) column or ORM attribute) holds."""
    if value is None:
        return None
    return value[: column.type.length]
