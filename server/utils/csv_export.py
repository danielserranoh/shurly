"""Phase 3.10.5 — CSV streaming helpers for analytics endpoints."""

import csv
import io
from collections.abc import Iterable, Iterator, Sequence

from fastapi.responses import StreamingResponse

# Phase 6.3 — a spreadsheet runs a cell that starts with one of these (OWASP
# "CSV Injection"). Campaign recipients come from uploaded CSVs, so a recipient
# named `=HYPERLINK(…)` would be a live formula for whoever opens an export.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def spreadsheet_safe(value: object) -> object:
    """
    A cell a spreadsheet shows as text instead of running it: text that starts
    like a formula gets a leading single quote, which Excel, Google Sheets and
    LibreOffice read as "this is text". Numbers and dates are left alone (a
    phone number like "+34…" gets the quote too: that's the trade-off).
    """
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def unquote_spreadsheet_text(value: str) -> str:
    """Undo `spreadsheet_safe`, for our own CSV import: an export uploaded back
    keeps its data instead of gaining a quote each round."""
    if value.startswith("'") and value[1:].startswith(_FORMULA_START):
        return value[1:]
    return value


def stream_csv(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    filename: str,
) -> StreamingResponse:
    """
    Yield a CSV response without buffering the whole file in memory.

    Using `csv.writer` over a per-row StringIO keeps quoting/escaping correct
    while still letting Starlette stream chunks to the client. Filename ends
    up as a `Content-Disposition: attachment` so curl + browsers both DTRT.
    Every cell, header included, goes through `spreadsheet_safe`.
    """

    def _generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([spreadsheet_safe(header) for header in headers])
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
        for row in rows:
            writer.writerow([spreadsheet_safe(cell) for cell in row])
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
