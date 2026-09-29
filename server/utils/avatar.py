"""
Phase 3.12 — what an uploaded avatar becomes: a 512×512 WebP, and nothing else.

Decoding the upload safely, and dropping its metadata, is `server/utils/images.py`'s, shared
with the organization's logo. A face is cropped to a square from its centre.
"""

from PIL import Image, ImageOps

from server.utils.images import (
    CONTENT_TYPE,
    MAX_SIDE,
    MAX_UPLOAD_BYTES,
    ImageRefused,
    decode,
    sniff,
    to_webp,
    too_big,
)

__all__ = [
    "CONTENT_TYPE",
    "MAX_SIDE",
    "MAX_UPLOAD_BYTES",
    "SIZE",
    "TOO_BIG",
    "AvatarRefused",
    "normalize",
    "sniff",
]

SIZE = 512
NOUN = "An avatar"
TOO_BIG = too_big(NOUN)

AvatarRefused = ImageRefused


def normalize(data: bytes) -> bytes:
    """The avatar to store for an upload: turned as the photo was taken, cropped to its
    centre, 512×512 WebP. Raises AvatarRefused (415 or 413)."""
    square = ImageOps.fit(decode(data, NOUN), (SIZE, SIZE), Image.Resampling.LANCZOS)
    return to_webp(square)
