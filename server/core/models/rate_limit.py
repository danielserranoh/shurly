"""
Phase 6.3 — rate-limit counters, one row per key (which limit, and whose).

In the database so both tasks share the counts and a deploy keeps them. The key
is an HMAC, never an address or an email (server/utils/rate_limit.py).
"""

from sqlalchemy import BigInteger, Column, Integer, String

from server.core import Base


class RateLimit(Base):
    __tablename__ = "rate_limits"

    key = Column(String(64), primary_key=True)
    # The start of the current fixed window, in seconds since the epoch. Rows idle
    # for an hour go when the limiter next writes.
    window_start = Column(BigInteger, nullable=False, index=True)
    count = Column(Integer, nullable=False)
