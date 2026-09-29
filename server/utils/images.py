"""
Phase 3.12, 3.14.4 — an uploaded image, decoded and drawn again: what the avatar and the
organization's logo share.

The upload is decoded and re-encoded as WebP, so what's stored carries no metadata: no EXIF
(the camera, and GPS for where the photo was taken), no XMP, no ICC profile. Pillow parses
untrusted input here, so:

- only the decoder the magic bytes name is tried (JPEG, PNG or WebP), whatever the request's
  Content-Type says. No SVG: it's a document, with scripts and links, not an image;
- the sides are checked before the pixels are loaded (4096 at most), and Pillow's own limit
  on pixels is set to match, so a decompression bomb is refused, not opened;
- Pillow is kept up to date (pyproject.toml): its CVEs matter here.

What each image becomes (a square, or its own shape) is up to its module:
`server/utils/avatar.py`, `server/utils/logo.py`.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SIDE = 4096
CONTENT_TYPE = "image/webp"

# Pillow refuses (DecompressionBombError) twice this many pixels, and warns above it.
Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE

UNREADABLE = "Upload a JPEG, PNG or WebP image."
TOO_MANY_PIXELS = "That image has too many pixels to open."


def too_big(noun: str) -> str:
    """The 413 for more than MAX_UPLOAD_BYTES: "An avatar can be 2 MB at most."."""
    return f"{noun} can be {MAX_UPLOAD_BYTES // (1024 * 1024)} MB at most."


def too_wide(noun: str) -> str:
    return f"{noun} can be {MAX_SIDE} pixels a side at most."


class ImageRefused(Exception):
    """An upload that can't be stored: the HTTP status to answer, and why."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def sniff(data: bytes) -> str | None:
    """The format the magic bytes name, as Pillow calls it; None for any other."""
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def decode(data: bytes, noun: str) -> Image.Image:
    """
    The upload's pixels, turned the way the EXIF says the photo was taken, in RGBA when it
    has transparency and RGB otherwise. `noun` names it in the refusals ("An avatar").
    Raises ImageRefused (415 or 413).
    """
    kind = sniff(data)
    if kind is None:
        raise ImageRefused(415, UNREADABLE)
    try:
        with Image.open(io.BytesIO(data), formats=[kind]) as upload:
            if max(upload.size) > MAX_SIDE:
                raise ImageRefused(413, too_wide(noun))
            # Loads the pixels, turned the way the EXIF says the photo was taken.
            turned = ImageOps.exif_transpose(upload)
            return turned.convert("RGBA" if turned.has_transparency_data else "RGB")
    except Image.DecompressionBombError:
        raise ImageRefused(413, TOO_MANY_PIXELS) from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise ImageRefused(415, UNREADABLE) from None


def to_webp(image: Image.Image, quality: int = 85) -> bytes:
    """`image` as WebP, with nothing from the upload riding along (EXIF, XMP, ICC)."""
    image.info.clear()
    out = io.BytesIO()
    image.save(out, "WEBP", quality=quality, method=4)
    return out.getvalue()
