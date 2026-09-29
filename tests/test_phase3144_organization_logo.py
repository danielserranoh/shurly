"""
Phase 3.14.4 — the organization's logo: `PUT`, `GET` and `DELETE /api/v1/organization/logo`.

The avatar's contract (tests/test_phase312_avatar.py), and its pipeline: the image is the
request body, a JPEG, PNG or WebP by its magic bytes, 2 MB at most, refused as it streams in,
decoded and re-encoded as WebP without metadata. But a logo isn't a face: it keeps its shape
(fit within 512×512, never cropped, never enlarged) and its transparency.

Owners and admins upload and remove it; every member sees it; someone outside the
organization gets a 404. `GET /organization` says its `logo_version`.
"""

import io

import pytest
from PIL import Image
from sqlalchemy import inspect

from server.core.models import Organization, OrgRole
from server.utils import logo as logo_utils
from server.utils import organization as org_service
from tests.test_phase312_avatar import _decoded, _image, _is, _jpeg_on_its_side, _jpeg_with_gps
from tests.test_phase3142_organization_roles import _events, _headers, _person

LOGO = "/api/v1/organization/logo"
IMMUTABLE = "private, max-age=31536000, immutable"
REVALIDATE = "private, no-cache"


@pytest.fixture
def team(db_session):
    return {
        "owner": _person(db_session, "owner@griddo.io", OrgRole.OWNER),
        "admin": _person(db_session, "admin@griddo.io", OrgRole.ADMIN),
        "member": _person(db_session, "member@griddo.io", OrgRole.MEMBER),
        "outsider": _person(db_session, "someone@elsewhere.com", None),
    }


@pytest.fixture
def owner(team):
    return _headers(team["owner"])


def _put(client, headers, data: bytes, content_type="image/png"):
    return client.put(LOGO, headers={**headers, "Content-Type": content_type}, content=data)


def _get(client, headers, **params):
    return client.get(LOGO, headers=headers, params=params)


def _org(client, headers) -> dict:
    return client.get("/api/v1/organization", headers=headers).json()


def _png(size=(200, 100), color="red", mode="RGB") -> bytes:
    return _image("PNG", size=size, color=color, mode=mode)


class TestUpload:
    def test_stores_a_webp_and_versions_the_organization(self, client, owner):
        response = _put(client, owner, _png())

        assert response.status_code == 200
        version = response.json()["logo_version"]
        assert version
        assert response.json()["role"] == "owner"
        assert _org(client, owner)["logo_version"] == version

        stored = _get(client, owner)
        assert stored.status_code == 200
        assert stored.headers["content-type"] == "image/webp"
        assert _decoded(stored.content).format == "WEBP"

    def test_takes_jpeg_and_webp(self, client, owner):
        assert _put(client, owner, _image("JPEG"), "image/jpeg").status_code == 200
        assert _put(client, owner, _image("WEBP"), "image/webp").status_code == 200

    def test_the_magic_bytes_decide_not_the_content_type(self, client, owner):
        assert _put(client, owner, _image("JPEG"), "image/png").status_code == 200

    def test_replacing_it_changes_the_version(self, client, owner):
        first = _put(client, owner, _png(color="red")).json()["logo_version"]
        second = _put(client, owner, _png(color="blue")).json()["logo_version"]

        assert first != second
        assert _is(_decoded(_get(client, owner).content).getpixel((100, 50)), "blue")

    def test_needs_a_signed_in_person(self, client):
        assert client.put(LOGO, content=_png()).status_code == 401
        assert client.get(LOGO).status_code == 401
        assert client.delete(LOGO).status_code == 401

    def test_writes_the_event_log(self, client, owner, team, capsys):
        _put(client, owner, _png())
        client.delete(LOGO, headers=owner)

        events = _events(capsys.readouterr().err, "org.logo_changed")
        assert [(e["actor_id"], e["change"]) for e in events] == [
            (str(team["owner"].id), "uploaded"),
            (str(team["owner"].id), "removed"),
        ]


class TestWhatIsKept:
    def test_a_wide_logo_keeps_its_shape(self, client, owner):
        """Not cropped to a square: fit within 512×512."""
        wide = Image.new("RGB", (2000, 500), "blue")
        wide.paste("red", (0, 0, 100, 500))  # a red band on the left, which a crop would lose
        buffer = io.BytesIO()
        wide.save(buffer, "PNG")
        _put(client, owner, buffer.getvalue())

        image = _decoded(_get(client, owner).content)
        assert image.size == (512, 128)
        assert _is(image.getpixel((5, 64)), "red")
        assert _is(image.getpixel((500, 64)), "blue")

    def test_a_tall_logo_keeps_its_shape(self, client, owner):
        _put(client, owner, _png(size=(300, 1200)))

        assert _decoded(_get(client, owner).content).size == (128, 512)

    def test_a_small_logo_isnt_enlarged(self, client, owner):
        _put(client, owner, _png(size=(120, 40)))

        assert _decoded(_get(client, owner).content).size == (120, 40)

    def test_keeps_transparency(self, client, owner):
        logo = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        logo.paste((255, 0, 0, 255), (50, 25, 150, 75))
        buffer = io.BytesIO()
        logo.save(buffer, "PNG")
        _put(client, owner, buffer.getvalue())

        image = _decoded(_get(client, owner).content)
        assert image.mode == "RGBA"
        assert image.getpixel((5, 5))[3] == 0
        assert image.getpixel((100, 50))[3] == 255 and _is(image.getpixel((100, 50)), "red")

    def test_no_metadata_reaches_the_database(self, client, owner, db_session):
        _put(client, owner, _jpeg_with_gps(), "image/jpeg")

        stored = org_service.get_or_create_default_organization(db_session).logo
        image = _decoded(stored)
        assert not image.getexif()
        assert "exif" not in image.info and "xmp" not in image.info
        assert b"EXIF" not in stored and b"XMP " not in stored

    def test_the_photo_is_turned_the_way_it_was_taken(self, client, owner):
        _put(client, owner, _jpeg_on_its_side(), "image/jpeg")

        image = _decoded(_get(client, owner).content)
        assert image.size == (100, 200)  # stored 200×100, shown turned a quarter
        assert _is(image.getpixel((50, 50)), "red") and _is(image.getpixel((50, 150)), "blue")


class TestRefused:
    @pytest.mark.parametrize(
        "data",
        [
            b"",
            b"hello, not an image",
            _image("GIF"),
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,  # PNG's magic, nothing readable after
        ],
    )
    def test_anything_but_a_readable_jpeg_png_or_webp(self, client, owner, data):
        response = _put(client, owner, data, "image/svg+xml")

        assert response.status_code == 415
        assert "JPEG, PNG or WebP" in response.json()["detail"]

    def test_more_than_2_mb(self, client, owner):
        response = _put(client, owner, b"\x89PNG\r\n\x1a\n" + b"\x00" * logo_utils.MAX_UPLOAD_BYTES)

        assert response.status_code == 413
        assert response.json()["detail"] == "A logo can be 2 MB at most."

    def test_more_than_2_mb_without_a_length_is_cut_off_as_it_streams(self, client, owner):
        def chunks():
            yield b"\x89PNG\r\n\x1a\n"
            for _ in range(logo_utils.MAX_UPLOAD_BYTES // 65536 + 1):
                yield b"\x00" * 65536

        response = client.put(
            LOGO, headers={**owner, "Content-Type": "image/png"}, content=chunks()
        )

        assert response.status_code == 413

    def test_more_than_4096_pixels_a_side(self, client, owner):
        response = _put(client, owner, _png(size=(4097, 1)))

        assert response.status_code == 413
        assert response.json()["detail"] == "A logo can be 4096 pixels a side at most."

    def test_a_decompression_bomb(self, client, owner, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)

        response = _put(client, owner, _png(size=(64, 64)))

        assert response.status_code == 413
        assert "too many pixels" in response.json()["detail"]

    def test_a_refused_upload_keeps_the_logo_there_was(self, client, owner):
        version = _put(client, owner, _png()).json()["logo_version"]
        _put(client, owner, b"not an image")

        assert _org(client, owner)["logo_version"] == version


class TestWho:
    def test_an_admin_uploads_and_removes_it(self, client, team):
        admin = _headers(team["admin"])

        assert _put(client, admin, _png()).status_code == 200
        assert client.delete(LOGO, headers=admin).status_code == 204

    def test_a_member_sees_it(self, client, owner, team):
        version = _put(client, owner, _png()).json()["logo_version"]
        member = _headers(team["member"])

        assert _org(client, member)["logo_version"] == version
        assert _get(client, member, v=version).status_code == 200

    def test_a_member_cant_upload_or_remove_it(self, client, owner, team):
        version = _put(client, owner, _png()).json()["logo_version"]
        member = _headers(team["member"])

        upload = _put(client, member, _png(color="blue"))
        assert upload.status_code == 403
        assert "owners and admins" in upload.json()["detail"]
        assert client.delete(LOGO, headers=member).status_code == 403
        assert _org(client, owner)["logo_version"] == version

    def test_a_members_upload_is_refused_before_it_is_read(self, client, team):
        """The role is checked first: more than 2 MB is a 403, not a 413."""
        member = _headers(team["member"])

        response = _put(client, member, b"\x89PNG\r\n\x1a\n" + b"\x00" * (3 * 1024 * 1024))

        assert response.status_code == 403

    def test_an_outsider_gets_a_404(self, client, owner, team):
        version = _put(client, owner, _png()).json()["logo_version"]
        outsider = _headers(team["outsider"])

        assert _get(client, outsider, v=version).status_code == 404
        assert _get(client, outsider).status_code == 404
        assert _put(client, outsider, _png()).status_code == 404
        assert client.delete(LOGO, headers=outsider).status_code == 404
        assert _org(client, owner)["logo_version"] == version


class TestServing:
    def test_a_404_without_one(self, client, owner):
        assert _org(client, owner)["logo_version"] is None
        response = _get(client, owner)

        assert response.status_code == 404
        assert response.json()["detail"] == "No logo"

    def test_the_versioned_url_is_immutable(self, client, owner):
        version = _put(client, owner, _png()).json()["logo_version"]

        response = _get(client, owner, v=version)

        assert response.headers["cache-control"] == IMMUTABLE
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"] == "inline"
        assert response.headers["etag"] == f'"{version}"'

    @pytest.mark.parametrize("params", [{}, {"v": "20000101000000000000"}])
    def test_any_other_url_revalidates(self, client, owner, params):
        _put(client, owner, _png())

        response = _get(client, owner, **params)

        assert response.status_code == 200
        assert response.headers["cache-control"] == REVALIDATE
        assert response.headers["x-content-type-options"] == "nosniff"

    @pytest.mark.parametrize("tag", ['"{v}"', 'W/"{v}"', '"other", "{v}"', "*"])
    def test_a_matching_etag_is_a_304(self, client, owner, tag):
        version = _put(client, owner, _png()).json()["logo_version"]

        response = client.get(LOGO, headers={**owner, "If-None-Match": tag.format(v=version)})

        assert response.status_code == 304
        assert response.content == b""
        assert response.headers["etag"] == f'"{version}"'

    def test_an_old_etag_gets_the_image(self, client, owner):
        _put(client, owner, _png())

        response = client.get(LOGO, headers={**owner, "If-None-Match": '"old"'})

        assert response.status_code == 200


class TestRemoving:
    def test_back_to_the_initial(self, client, owner):
        _put(client, owner, _png())

        assert client.delete(LOGO, headers=owner).status_code == 204
        assert _get(client, owner).status_code == 404
        assert _org(client, owner)["logo_version"] is None

    def test_twice_is_fine(self, client, owner):
        assert client.delete(LOGO, headers=owner).status_code == 204
        assert client.delete(LOGO, headers=owner).status_code == 204

    def test_keeps_the_organization(self, client, owner):
        before = _org(client, owner)
        _put(client, owner, _png())
        client.delete(LOGO, headers=owner)

        assert _org(client, owner) == before


class TestTheBytesStayUnloaded:
    """The logo column is deferred: reading the organization never loads the image."""

    def test_reading_the_organization(self, client, owner, db_session):
        _put(client, owner, _png())
        db_session.expire_all()

        assert _org(client, owner)["logo_version"]
        organization = db_session.query(Organization).one()
        assert organization.logo_version
        assert "logo" in inspect(organization).unloaded

    def test_answering_a_304(self, client, owner, db_session):
        version = _put(client, owner, _png()).json()["logo_version"]
        db_session.expire_all()

        client.get(LOGO, headers={**owner, "If-None-Match": f'"{version}"'})

        organization = db_session.query(Organization).one()
        assert "logo" in inspect(organization).unloaded
