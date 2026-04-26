"""Phase 3.10.5 — CSV streaming helpers for analytics endpoints."""

import csv
import io
from typing import Iterable, Iterator, Sequence

from fastapi.responses import StreamingResponse


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
    """

    def _generate() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        yield buf.getvalue()
        buf.seek(0)
        buf.truncate()
        for row in rows:
            writer.writerow(row)
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
