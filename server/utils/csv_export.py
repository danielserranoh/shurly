"""Phase 3.10.5 — CSV streaming helpers for analytics endpoints."""

import csv
import io
import re
from collections.abc import Iterable, Iterator, Sequence
from urllib.parse import quote

from fastapi.responses import StreamingResponse

# Phase 6.3 — a spreadsheet runs a cell that starts with one of these (OWASP
# "CSV Injection"). Campaign recipients come from uploaded CSVs, so a recipient
# named `=HYPERLINK(…)` would be a live formula for whoever opens an export.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
_CHUNK = 64 * 1024  # characters per chunk streamed


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


_NOT_PLAIN = re.compile(r"[^A-Za-z0-9._ -]")


def content_disposition(filename: str) -> str:
    """
    `attachment`, with the filename twice (RFC 6266): a plain ASCII fallback in
    `filename`, and the real name, percent-encoded UTF-8, in `filename*` (RFC 5987),
    which browsers prefer. Phase 6.3: the name can come from a campaign's, i.e. user
    input. Without this, a name outside latin-1 ("Q4 🚀", "东京") made the export
    fail, and quotes, CR/LF or slashes went into the header as they were.
    """
    printable = "".join(char for char in filename if char.isprintable())[:120]
    stem, dot, extension = printable.rpartition(".")
    if not dot:
        stem, extension = printable, ""
    fallback = _NOT_PLAIN.sub("_", stem).strip() or "export"
    if extension:
        fallback = f"{fallback}.{_NOT_PLAIN.sub('_', extension)}"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(printable, safe='')}"


def stream_csv(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    filename: str,
) -> StreamingResponse:
    """
    Yield a CSV response without buffering the whole file in memory.

    Using `csv.writer` over a StringIO keeps quoting/escaping correct while
    still letting Starlette stream chunks to the client. Filename ends up as a
    `Content-Disposition: attachment` so curl + browsers both DTRT. Every
    cell, header included, goes through `spreadsheet_safe`.

    Phase 3.16 — chunks of about `_CHUNK` characters, not a row each: Starlette
    iterates a sync generator in its threadpool, a thread hop per chunk, which
    made 10,000 rows take most of a second.
    """

    def _generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([spreadsheet_safe(header) for header in headers])
        for row in rows:
            writer.writerow([spreadsheet_safe(cell) for cell in row])
            if buf.tell() >= _CHUNK:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        if buf.tell():
            yield buf.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": content_disposition(filename),
            "Cache-Control": "no-store",
        },
    )
