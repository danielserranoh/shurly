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


# A header stored in a Text column fits at any length, so a scanner could store tens of KB of it
# on every hit, up to what the load balancer lets through. Real ones are a few hundred characters.
# Only what's stored is cut: bot detection and the redirect rules read the whole header first.
USER_AGENT_LENGTH = 1024
REFERER_LENGTH = 2048


def stored_user_agent(value: str | None) -> str | None:
    """A user agent as a visit keeps it: its first USER_AGENT_LENGTH characters."""
    return None if value is None else value[:USER_AGENT_LENGTH]


def stored_referer(value: str | None) -> str | None:
    """A referrer as a visit keeps it: its first REFERER_LENGTH characters."""
    return None if value is None else value[:REFERER_LENGTH]
