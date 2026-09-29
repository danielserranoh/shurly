"""
Passwords are bcrypt hashes, made and checked by bcrypt itself (server/core/auth.py), without passlib.
passlib is unmaintained since 2020, and its bcrypt self-test hashes a 255-byte secret, which bcrypt 5
refuses: with it, every hash failed (Dependabot's #182).

- bcrypt reads at most 72 bytes. Setting a longer password is a 422, at register, set and change: its end
  would be ignored. The limit is in bytes, so it's fewer characters with accented letters or emoji.
- Signing in still reads the first 72 bytes, as the old code did. A password set longer before, hashed
  from its first 72 bytes, still works: pinned with hashes the old passlib code made.
"""

import re
from pathlib import Path

import bcrypt
import pytest

from server.core.auth import hash_password, verify_password
from server.core.models import User

ROOT = Path(__file__).parents[1]

# Made by the old code (passlib 1.7.4 on bcrypt 4.3.0, through hash_password), on 2026-09-29.
OLD_HASH = (
    "$2b$12$VRP5iHefRbZL8UO92Pe84OfqKWaXcx69mu5M8rAKV5o.n/2IAYDAS"  # correct horse battery staple
)
OLD_LONG_HASH = "$2b$12$C5Qmg7c/VjRl6bzeAmq9JeanZ8w0cz76obAMVUaOXnvwlLsUYrhwO"  # "é" * 40, 80 bytes

TOO_LONG = {
    "accented, 37 characters": "é" * 37,  # 74 bytes
    "emoji, 19 characters": "😀" * 19,  # 76 bytes
    "plain, 73 characters": "a" * 73,
}


class TestHashes:
    def test_the_old_codes_hashes_still_verify(self):
        assert verify_password("correct horse battery staple", OLD_HASH)
        assert not verify_password("correct horse battery stapler", OLD_HASH)

    def test_a_password_set_longer_than_72_bytes_before_still_verifies(self):
        """The old code hashed its first 72 bytes: 36 "é", two bytes each."""
        assert verify_password("é" * 40, OLD_LONG_HASH)
        assert verify_password("é" * 36, OLD_LONG_HASH)
        assert not verify_password("é" * 35, OLD_LONG_HASH)

    def test_new_hashes_are_bcrypts_2b_with_12_rounds(self):
        hashed = hash_password("correct horse battery staple")

        assert hashed.startswith("$2b$12$")
        assert verify_password("correct horse battery staple", hashed)
        assert not verify_password("correct horse battery stapler", hashed)

    def test_no_password_is_too_long_to_check(self):
        """bcrypt 5 raises past 72 bytes; a check never hands it more."""
        assert verify_password("x" * 10_000, hash_password("x" * 72))

    def test_a_character_is_never_cut_in_half(self):
        """73 bytes: the last "é" doesn't fit, and goes whole, as the old code did."""
        hashed = hash_password("a" + "é" * 35)

        assert verify_password("a" + "é" * 36, hashed)

    @pytest.mark.parametrize("hashed", ["", "not-a-hash", "$2b$12$short"])
    def test_something_that_isnt_a_bcrypt_hash_verifies_nothing(self, hashed):
        assert verify_password("anything", hashed) is False

    def test_bcrypt_5_and_no_passlib(self):
        assert int(bcrypt.__version__.split(".")[0]) >= 5
        dependencies = (ROOT / "pyproject.toml").read_text()
        assert not re.search(r'^\s*"passlib', dependencies, re.MULTILINE)  # no such dependency


class TestTooLongToSet:
    MESSAGE = "72 bytes"

    @pytest.mark.parametrize("password", TOO_LONG.values(), ids=TOO_LONG.keys())
    def test_register(self, client, allow_password_signup, password):
        response = client.post(
            "/api/v1/auth/register", json={"email": "ana@example.com", "password": password}
        )

        assert response.status_code == 422
        assert self.MESSAGE in response.text

    def test_exactly_72_bytes_is_fine(self, client, allow_password_signup):
        response = client.post(
            "/api/v1/auth/register", json={"email": "ana@example.com", "password": "é" * 36}
        )

        assert response.status_code == 201, response.text

    @pytest.mark.parametrize("password", TOO_LONG.values(), ids=TOO_LONG.keys())
    def test_set_and_change(self, client, auth_headers, password):
        set_it = client.put(
            "/api/v1/auth/password", json={"new_password": password}, headers=auth_headers
        )
        change_it = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "whatever-1", "new_password": password},
            headers=auth_headers,
        )

        for response in (set_it, change_it):
            assert response.status_code == 422
            assert self.MESSAGE in response.text

    def test_the_message_says_why_in_plain_words(self, client, allow_password_signup):
        response = client.post(
            "/api/v1/auth/register", json={"email": "ana@example.com", "password": "é" * 37}
        )

        (error,) = response.json()["detail"]
        assert error["msg"].startswith("Too long: a password can be at most 72 bytes.")
        assert "accent" in error["msg"] and "emoji" in error["msg"]


class TestSignIn:
    def test_a_long_password_set_before_still_signs_in(self, client, db_session):
        db_session.add(User(email="long@example.com", password_hash=OLD_LONG_HASH, is_active=True))
        db_session.commit()

        response = client.post(
            "/api/v1/auth/login", json={"email": "long@example.com", "password": "é" * 40}
        )

        assert response.status_code == 200, response.text

    def test_a_long_wrong_password_is_just_refused(self, client, db_session):
        db_session.add(User(email="ana@example.com", password_hash=OLD_HASH, is_active=True))
        db_session.commit()

        response = client.post(
            "/api/v1/auth/login", json={"email": "ana@example.com", "password": "x" * 500}
        )

        assert response.status_code == 401
