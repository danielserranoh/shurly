"""
ROADMAP 6.3 — a NUL character (U+0000) in a request is a 4xx, never a 500.

PostgreSQL can't hold NUL in text: psycopg2 refuses it, and every request carrying one answered
500, the public short-link host's included, so anyone could make it. uvicorn's parsers (httptools
and h11) already refuse NUL in a header, with a 400 of their own.
"""

import json

from starlette.requests import Request
from starlette.responses import JSONResponse

MESSAGE = "A request can't contain a NUL character (U+0000)"
TEXT_MESSAGE = "Text can't contain a NUL character (U+0000)"
PSYCOPG_NUL = "cannot contain NUL (0x00) characters"  # psycopg2's ValueError says this


class NulMiddleware:
    """
    Before any route, the MCP's mount included: a 400 for NUL in the path or the query (plain,
    even on the short-link host: no link has one); a 422 in FastAPI's shape for NUL in a JSON
    body, where it is. A JSON body is parsed only when its bytes hold a NUL or its escape, so a
    request without one costs a byte search, not a second parse.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        query = scope.get("query_string", b"")
        if "\x00" in scope["path"] or b"%00" in query or b"\x00" in query:
            await JSONResponse({"detail": MESSAGE}, status_code=400)(scope, receive, send)
            return
        if not _is_json(scope):
            await self.app(scope, receive, send)
            return
        body, receive = await _buffered(receive)
        found = _nul_in(body) if b"\x00" in body or b"\\u0000" in body else None
        if found is None:
            await self.app(scope, receive, send)
            return
        where, text = found
        error = {"type": "string_nul", "loc": ["body", *where], "msg": TEXT_MESSAGE, "input": text}
        await JSONResponse({"detail": [error]}, status_code=422)(scope, receive, send)


async def nul_value_error(request: Request, exc: ValueError):
    """The safety net for what the middleware doesn't see: psycopg2 refusing a NUL is a 422.
    Any other ValueError is the 500 it always was."""
    if PSYCOPG_NUL not in str(exc):
        raise exc
    return JSONResponse({"detail": TEXT_MESSAGE}, status_code=422)


def _is_json(scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == b"content-type":
            media = value.split(b";", 1)[0].strip().lower()
            return media == b"application/json" or media.endswith(b"+json")
    return False


async def _buffered(receive):
    """The whole body, and a `receive` that hands it on as one message, then what follows."""
    chunks, after = [], []
    while True:
        message = await receive()
        if message["type"] != "http.request":
            after.append(message)  # the client went away: the app hears it after the body
            break
        chunks.append(message.get("body", b""))
        if not message.get("more_body", False):
            break
    body = b"".join(chunks)
    pending = [{"type": "http.request", "body": body, "more_body": False}, *after]

    async def replay():
        return pending.pop(0) if pending else await receive()

    return body, replay


def _nul_in(body: bytes):
    """Where a NUL is in a JSON body, and the text holding it: None when there's none, or when
    the body isn't JSON (the route answers that itself)."""
    try:
        value = json.loads(body)
    except ValueError:
        return None
    return _find(value, [])


def _find(value, where: list):
    if isinstance(value, str):
        return (where, value) if "\x00" in value else None
    if isinstance(value, dict):
        for key, item in value.items():
            if "\x00" in key:
                return [*where, key], key
            found = _find(item, [*where, key])
            if found:
                return found
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found = _find(item, [*where, index])
            if found:
                return found
    return None
