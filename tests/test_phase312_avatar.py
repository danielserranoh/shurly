"""
Phase 3.12 — the avatar: `PUT`, `GET` and `DELETE /api/v1/auth/me/avatar`.

The upload is the image itself (the request body), a JPEG, PNG or WebP by its magic
bytes, 2 MB at most, refused as it streams in. The server decodes it and re-encodes a
512×512 WebP without metadata, so EXIF, GPS included, never reaches the database. The
GET answers the stored bytes: immutable in the browser's cache only for the `?v=` URL of
the current version, revalidated with its ETag otherwise.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import inspect

from server.core.models import UserProfile
from server.utils import avatar

AVATAR = "/api/v1/auth/me/avatar"
IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "private, no-cache"


def _image(fmt: str = "JPEG", size=(200, 100), color="red", mode="RGB", **save) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, fmt, **save)
    return buffer.getvalue()


def _jpeg_with_gps() -> bytes:
    """A phone photo: the camera, and where it was taken."""
    exif = Image.Exif()
    exif[0x010F] = "Phone maker"  # Make
    exif[0x0110] = "Phone model"  # Model
    exif.get_ifd(0x8825).update({1: "N", 2: (40.0, 25.0, 0.0), 3: "W", 4: (3.0, 42.0, 0.0)})
    data = _image(size=(640, 480), exif=exif)
    assert Image.open(io.BytesIO(data)).getexif().get_ifd(0x8825), "the test photo has GPS"
    return data


def _jpeg_on_its_side() -> bytes:
    """Stored 200×100, red left and blue right, with EXIF Orientation 6: shown turned a
    quarter clockwise, so red on top and blue below."""
    image = Image.new("RGB", (200, 100), "red")
    image.paste("blue", (100, 0, 200, 100))
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def _put(client, headers, data: bytes, content_type="image/jpeg"):
    return client.put(AVATAR, headers={**headers, "Content-Type": content_type}, content=data)


def _get(client, headers, **params):
    return client.get(AVATAR, headers=headers, params=params)


def _decoded(body: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(body))
    image.load()
    return image


def _is(pixel, color: str) -> bool:
    r, g, b = pixel[:3]
    return {"red": r > 200 and g < 60 and b < 60, "blue": b > 200 and r < 60 and g < 60}[color]


class TestUpload:
    def test_stores_a_512_webp_and_versions_the_profile(self, client, auth_headers):
        response = _put(client, auth_headers, _image())

        assert response.status_code == 200
        version = response.json()["avatar_version"]
        assert version
        me = client.get("/api/v1/auth/me", headers=auth_headers).json()
        assert me["profile"]["avatar_version"] == version

        stored = _get(client, auth_headers)
        assert stored.status_code == 200
        assert stored.headers["content-type"] == "image/webp"
        image = _decoded(stored.content)
        assert (image.format, image.size) == ("WEBP", (512, 512))

    def test_takes_png_and_webp(self, client, auth_headers):
        assert _put(client, auth_headers, _image("PNG"), "image/png").status_code == 200
        assert _put(client, auth_headers, _image("WEBP"), "image/webp").status_code == 200

    def test_keeps_transparency(self, client, auth_headers):
        _put(client, auth_headers, _image("PNG", mode="RGBA", color=(0, 0, 0, 0)), "image/png")

        image = _decoded(_get(client, auth_headers).content)
        assert image.mode == "RGBA"
        assert image.getpixel((10, 10))[3] == 0

    def test_the_magic_bytes_decide_not_the_content_type(self, client, auth_headers):
        assert _put(client, auth_headers, _image("JPEG"), "image/png").status_code == 200

    def test_replacing_it_changes_the_version(self, client, auth_headers):
        first = _put(client, auth_headers, _image(color="red")).json()["avatar_version"]
        second = _put(client, auth_headers, _image(color="blue")).json()["avatar_version"]

        assert first != second
        assert _is(_decoded(_get(client, auth_headers).content).getpixel((256, 256)), "blue")

    def test_needs_a_signed_in_person(self, client):
        assert client.put(AVATAR, content=_image()).status_code == 401
        assert client.get(AVATAR).status_code == 401
        assert client.delete(AVATAR).status_code == 401


class TestWhatIsKept:
    def test_no_metadata_reaches_the_database(self, client, auth_headers, db_session, test_user):
        _put(client, auth_headers, _jpeg_with_gps())

        stored = db_session.get(UserProfile, test_user.id).avatar
        image = _decoded(stored)
        assert not image.getexif()
        assert "exif" not in image.info and "xmp" not in image.info
        # The WebP container has no EXIF or XMP chunk at all.
        assert b"EXIF" not in stored and b"XMP " not in stored

    def test_the_photo_is_turned_the_way_it_was_taken(self, client, auth_headers):
        _put(client, auth_headers, _jpeg_on_its_side())

        image = _decoded(_get(client, auth_headers).content)
        assert _is(image.getpixel((100, 100)), "red") and _is(image.getpixel((412, 100)), "red")
        assert _is(image.getpixel((100, 412)), "blue") and _is(image.getpixel((412, 412)), "blue")

    def test_a_rectangle_is_cropped_to_its_centre(self, client, auth_headers):
        wide = Image.new("RGB", (300, 100), "blue")
        wide.paste("red", (100, 0, 200, 100))
        buffer = io.BytesIO()
        wide.save(buffer, "PNG")
        _put(client, auth_headers, buffer.getvalue(), "image/png")

        image = _decoded(_get(client, auth_headers).content)
        assert all(_is(image.getpixel(xy), "red") for xy in [(20, 20), (492, 20), (256, 492)])


class TestRefused:
    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"hello, not an image",
            _image("GIF"),
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,  # PNG's magic, nothing readable after
        ],
    )
    def test_anything_but_a_readable_jpeg_png_or_webp(self, client, auth_headers, data):
        response = _put(client, auth_headers, data)

        assert response.status_code == 415
        assert "JPEG, PNG or WebP" in response.json()["detail"]

    def test_more_than_2_mb(self, client, auth_headers):
        too_big = b"\xff\xd8\xff" + b"\x00" * avatar.MAX_UPLOAD_BYTES

        response = _put(client, auth_headers, too_big)

        assert response.status_code == 413
        assert "2 MB" in response.json()["detail"]

    def test_more_than_2_mb_without_a_length_is_cut_off_as_it_streams(self, client, auth_headers):
        def chunks():
            yield b"\xff\xd8\xff"
            for _ in range(avatar.MAX_UPLOAD_BYTES // 65536 + 1):
                yield b"\x00" * 65536

        response = client.put(
            AVATAR, headers={**auth_headers, "Content-Type": "image/jpeg"}, content=chunks()
        )

        assert response.status_code == 413

    def test_more_than_4096_pixels_a_side(self, client, auth_headers):
        response = _put(client, auth_headers, _image("PNG", size=(4097, 1)), "image/png")

        assert response.status_code == 413
        assert "4096" in response.json()["detail"]

    def test_a_decompression_bomb(self, client, auth_headers, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)

        response = _put(client, auth_headers, _image("PNG", size=(64, 64)), "image/png")

        assert response.status_code == 413

    def test_the_limit_on_pixels_is_set(self):
        assert Image.MAX_IMAGE_PIXELS == avatar.MAX_SIDE * avatar.MAX_SIDE

    def test_a_refused_upload_keeps_the_avatar_there_was(self, client, auth_headers):
        version = _put(client, auth_headers, _image()).json()["avatar_version"]
        _put(client, auth_headers, b"not an image")

        me = client.get("/api/v1/auth/me", headers=auth_headers).json()
        assert me["profile"]["avatar_version"] == version


class TestServing:
    def test_a_404_without_one(self, client, auth_headers):
        assert _get(client, auth_headers).status_code == 404

    def test_a_404_with_a_profile_but_no_avatar(self, client, auth_headers):
        client.patch("/api/v1/auth/me/profile", headers=auth_headers, json={"first_name": "Ana"})

        assert _get(client, auth_headers).status_code == 404

    def test_the_versioned_url_is_immutable(self, client, auth_headers):
        version = _put(client, auth_headers, _image()).json()["avatar_version"]

        response = _get(client, auth_headers, v=version)

        assert response.headers["cache-control"] == IMMUTABLE
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"] == "inline"
        assert response.headers["etag"] == f'"{version}"'

    @pytest.mark.parametrize("params", [{}, {"v": "20000101000000000000"}])
    def test_any_other_url_revalidates(self, client, auth_headers, params):
        _put(client, auth_headers, _image())

        response = _get(client, auth_headers, **params)

        assert response.status_code == 200
        assert response.headers["cache-control"] == REVALIDATE

    @pytest.mark.parametrize("tag", ['"{v}"', 'W/"{v}"', '"other", "{v}"', "*"])
    def test_a_matching_etag_is_a_304(self, client, auth_headers, tag):
        version = _put(client, auth_headers, _image()).json()["avatar_version"]

        response = client.get(
            AVATAR, headers={**auth_headers, "If-None-Match": tag.format(v=version)}
        )

        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == f'"{version}"'

    def test_an_old_etag_gets_the_image(self, client, auth_headers):
        _put(client, auth_headers, _image())

        response = client.get(AVATAR, headers={**auth_headers, "If-None-Match": '"old"'})

        assert response.status_code == 200


class TestRemoving:
    def test_back_to_the_initial(self, client, auth_headers):
        _put(client, auth_headers, _image())

        assert client.delete(AVATAR, headers=auth_headers).status_code == 204
        assert _get(client, auth_headers).status_code == 404
        me = client.get("/api/v1/auth/me", headers=auth_headers).json()
        assert me["profile"]["avatar_version"] is None

    def test_twice_is_fine(self, client, auth_headers):
        assert client.delete(AVATAR, headers=auth_headers).status_code == 204
        assert client.delete(AVATAR, headers=auth_headers).status_code == 204

    def test_keeps_the_rest_of_the_profile(self, client, auth_headers):
        client.patch("/api/v1/auth/me/profile", headers=auth_headers, json={"first_name": "Ana"})
        _put(client, auth_headers, _image())
        client.delete(AVATAR, headers=auth_headers)

        me = client.get("/api/v1/auth/me", headers=auth_headers).json()
        assert me["profile"]["first_name"] == "Ana"


class TestTheBytesStayUnloaded:
    """The avatar column is deferred: reading or saving the profile never loads the image."""

    def test_reading_the_profile(self, client, auth_headers, db_session, test_user):
        _put(client, auth_headers, _image())
        db_session.expire_all()

        profile = db_session.get(UserProfile, test_user.id)
        assert profile.avatar_version
        assert "avatar" in inspect(profile).unloaded

    def test_saving_the_profile(self, client, auth_headers, db_session, test_user):
        _put(client, auth_headers, _image())
        db_session.expire_all()

        response = client.patch(
            "/api/v1/auth/me/profile", headers=auth_headers, json={"first_name": "Ana"}
        )

        assert response.json()["avatar_version"]
        profile = db_session.get(UserProfile, test_user.id)
        assert "avatar" in inspect(profile).unloaded

    def test_answering_a_304(self, client, auth_headers, db_session, test_user):
        version = _put(client, auth_headers, _image()).json()["avatar_version"]
        db_session.expire_all()

        client.get(AVATAR, headers={**auth_headers, "If-None-Match": f'"{version}"'})

        profile = db_session.get(UserProfile, test_user.id)
        assert "avatar" in inspect(profile).unloaded
