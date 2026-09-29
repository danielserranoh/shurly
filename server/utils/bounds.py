"""
Phase 6.3 — the largest numbers a request may carry, far past anything real. Past them a query's
OFFSET, or an integer column, overflows: the request answered 500 where it now answers 422.
`tests/test_bounded_numbers.py` checks every integer the API and the MCP take has bounds.
"""

MAX_SKIP = 1_000_000_000  # rows a list skips
MAX_PAGE = 1_000_000  # a page's number, from 1: times the largest page size, still far from int64
INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1  # what an Integer column holds, in PostgreSQL
