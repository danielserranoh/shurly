"""
Phase 3.12, 3.14.4 — an image kept in the database, over HTTP: the avatar's and the
organization logo's shared contract.

- The upload is the request body, refused (413) as soon as it passes the cap, rather than
  read whole first (`read_capped`).
- The GET answers the stored bytes (`image_response`). The `?v=<version>` URL of the current
  version is immutable in the browser's cache; any other, the bare one included, is
  revalidated against the ETag, and a matching If-None-Match is a 304 that never loads the
  (deferred) bytes. `nosniff`, and `inline`, always.

The frontend fetches these with the bearer header and shows them through an object URL: a
plain <img src> can't send the header.
"""

from collections.abc import Callable

from fastapi import HTTPException, Request, Response, status

IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "private, no-cache"

# The OpenAPI schema of an image body.
IMAGE_SCHEMA = {"schema": {"type": "string", "format": "binary"}}
UPLOAD_BODY = {
    "requestBody": {
        "required": True,
        "content": dict.fromkeys(("image/jpeg", "image/png", "image/webp"), IMAGE_SCHEMA),
    }
}


async def read_capped(request: Request, limit: int, too_big: str) -> bytes:
    """The body, refused (413, `too_big`) as soon as it passes `limit` bytes."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, too_big)
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, too_big)
    return bytes(body)


def image_response(
    request: Request,
    version: str,
    asked_version: str | None,
    content: Callable[[], tuple[bytes, str]],
) -> Response:
    """
    The stored image, `version` of it, asked for as `?v=asked_version`. `content` gives its
    bytes and content type, and is only called when they're sent (not for a 304).
    """
    headers = {
        "ETag": f'"{version}"',
        # Only this version's own URL is immutable; never the bare or a stale one.
        "Cache-Control": IMMUTABLE if asked_version == version else REVALIDATE,
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "inline",
    }
    if etag_matches(request.headers.get("if-none-match"), version):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    data, content_type = content()
    return Response(content=data, media_type=content_type, headers=headers)


def etag_matches(if_none_match: str | None, version: str) -> bool:
    """If-None-Match names this version (weak or strong), or is `*`."""
    if not if_none_match:
        return False
    tags = [tag.strip() for tag in if_none_match.split(",")]
    return "*" in tags or any(tag.removeprefix("W/") == f'"{version}"' for tag in tags)


def version_of(updated_at) -> str | None:
    """An image's version, from when it was uploaded: changes with each upload."""
    return None if updated_at is None else updated_at.strftime("%Y%m%d%H%M%S%f")
