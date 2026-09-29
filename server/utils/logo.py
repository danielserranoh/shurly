"""
Phase 3.14.4 — what an uploaded organization logo becomes: a WebP of at most 512×512.

Decoding the upload safely, and dropping its metadata, is `server/utils/images.py`'s, shared
with the avatar. A logo isn't a face, so unlike the avatar it's never cropped: it keeps its
shape, shrunk to fit within 512×512 (never enlarged, which would only blur it), and its
transparency, so it sits on any background.
"""

from PIL import Image

from server.utils.images import (
    CONTENT_TYPE,
    MAX_SIDE,
    MAX_UPLOAD_BYTES,
    ImageRefused,
    decode,
    to_webp,
    too_big,
)

__all__ = [
    "CONTENT_TYPE",
    "MAX_SIDE",
    "MAX_UPLOAD_BYTES",
    "SIZE",
    "TOO_BIG",
    "ImageRefused",
    "normalize",
]

# The longest side stored: it fits within SIZE×SIZE.
SIZE = 512
NOUN = "A logo"
TOO_BIG = too_big(NOUN)


def normalize(data: bytes) -> bytes:
    """The logo to store for an upload: its shape and transparency kept, within 512×512,
    WebP. Raises ImageRefused (415 or 413)."""
    logo = decode(data, NOUN)
    logo.thumbnail((SIZE, SIZE), Image.Resampling.LANCZOS)
    # Sharp edges and text: a higher quality than a photo's.
    return to_webp(logo, quality=90)
