"""
The API's datetimes, as RFC 3339 with an offset.

The columns hold naive UTC (`datetime.utcnow`), and Pydantic writes a naive datetime without an
offset: `2026-09-29T22:04:42.082199`. The OpenAPI schema says `"format": "date-time"`, which in
RFC 3339 needs one, and the MCP tools' outputSchema comes from it: strict clients (claude.ai)
rejected every response with a date. So every datetime the API returns is one of two types:

* `UtcDateTime`, a UTC time: written with `Z`, `2026-09-29T22:04:42.082199Z`. A naive value is
  taken as UTC, an aware one converted to it. Only the JSON output changes: input is parsed as
  `datetime` always was, and Python code keeps the value it set.
* `LocalDateTime`, the 3.16/3.17 analytics' local time, already in the viewer's zone and written
  with its offset (`2026-09-30T03:34:42+05:30`), as it always was: never turned into `Z`. It is
  Pydantic's `AwareDatetime`, so a naive value can't reach the output.

`tests/test_mcp_output_dates.py` fails on a response model's datetime field of neither type, and
on any tool's output a strict client would reject.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from pydantic import AwareDatetime, PlainSerializer


def as_utc(value: datetime) -> datetime:
    """`value` as an aware UTC datetime: naive is taken as UTC (how the columns store it)."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_isoformat(value: datetime | None) -> str | None:
    """For JSON built by hand (the curated MCP tools): what `UtcDateTime` writes, `Z` and all."""
    if value is None:
        return None
    return as_utc(value).isoformat().replace("+00:00", "Z")


# Returning an aware UTC datetime, Pydantic writes it with `Z`, and the JSON schema stays
# `{"type": "string", "format": "date-time"}`.
UTC_JSON = PlainSerializer(as_utc, return_type=datetime, when_used="json")

UtcDateTime = Annotated[datetime, UTC_JSON]

LocalDateTime = AwareDatetime
