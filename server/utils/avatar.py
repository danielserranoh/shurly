"""
Phase 3.12 — what an uploaded avatar becomes: a 512×512 WebP, and nothing else.

The upload is decoded and drawn again, so what's stored carries no metadata: no EXIF
(the camera, and GPS for where the photo was taken), no XMP, no ICC profile. Pillow
parses untrusted input here, so:

- only the decoder the magic bytes name is tried (JPEG, PNG or WebP), whatever the
  request's Content-Type says;
- the sides are checked before the pixels are loaded (4096 at most), and Pillow's own
  limit on pixels is set to match, so a decompression bomb is refused, not opened;
- Pillow is kept up to date (pyproject.toml): its CVEs matter here.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_SIDE = 4096
SIZE = 512
CONTENT_TYPE = "image/webp"

# Pillow refuses (DecompressionBombError) twice this many pixels, and warns above it.
Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE

UNREADABLE = "Upload a JPEG, PNG or WebP image."
TOO_BIG = "An avatar can be 2 MB at most."
TOO_WIDE = f"An avatar can be {MAX_SIDE} pixels a side at most."
TOO_MANY_PIXELS = "That image has too many pixels to open."


class AvatarRefused(Exception):
    """An upload that can't be an avatar: the HTTP status to answer, and why."""

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


def normalize(data: bytes) -> bytes:
    """The avatar to store for an upload: turned as the photo was taken, cropped to its
    centre, 512×512 WebP. Raises AvatarRefused (415 or 413)."""
    kind = sniff(data)
    if kind is None:
        raise AvatarRefused(415, UNREADABLE)
    try:
        with Image.open(io.BytesIO(data), formats=[kind]) as upload:
            if max(upload.size) > MAX_SIDE:
                raise AvatarRefused(413, TOO_WIDE)
            # Loads the pixels, turned the way the EXIF says the photo was taken.
            turned = ImageOps.exif_transpose(upload)
    except Image.DecompressionBombError:
        raise AvatarRefused(413, TOO_MANY_PIXELS) from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise AvatarRefused(415, UNREADABLE) from None

    square = ImageOps.fit(
        turned.convert("RGBA" if turned.has_transparency_data else "RGB"),
        (SIZE, SIZE),
        Image.Resampling.LANCZOS,
    )
    square.info.clear()  # nothing from the upload rides along
    out = io.BytesIO()
    square.save(out, "WEBP", quality=85, method=4)
    return out.getvalue()
