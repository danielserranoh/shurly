"""
A fake Google for the sign-in tests (Phase 3.13.6): its token endpoint and its
signing certs, answered through `httpx.MockTransport`, so nothing reaches the
network. The ID tokens are real RS256 JWTs, so google-auth's checks run as they
do against Google.
"""

import base64
import json
import time
from urllib.parse import parse_qs

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth import crypt
from google.auth import jwt as google_jwt

from server.utils.google_oidc import TOKEN_ENDPOINT

# Where google-auth fetches Google's signing certs.
CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"

CLIENT_ID = "shurly-test.apps.googleusercontent.com"
CLIENT_SECRET = "test-client-secret"
KEY_ID = "test-key"


def _key_pair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


# Once per test run: generating RSA keys is slow.
_GOOGLE_PRIVATE, _GOOGLE_PUBLIC = _key_pair()
_OTHER_PRIVATE, _ = _key_pair()


def _b64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


class FakeGoogle:
    """Google's side of one test. Change `claims` to change the next ID tokens."""

    def __init__(self):
        now = int(time.time())
        # A value of None leaves the claim out.
        self.claims: dict = {
            "iss": "https://accounts.google.com",
            "aud": CLIENT_ID,
            "sub": "1001",
            "email": "ana@griddo.io",
            "email_verified": True,
            "hd": "griddo.io",
            "iat": now,
            "exp": now + 3600,
        }
        self.signing = "google"  # or "other_key", or "none" (an unsigned token)
        self.token_error: str | None = None  # e.g. "invalid_grant": the endpoint answers 400
        self.unreachable = False
        self.cache_control: str | None = None  # on the certs response
        self.token_requests: list[dict[str, str]] = []
        self.issued_id_tokens: list[str] = []
        self.cert_fetches = 0

    def id_token(self) -> str:
        payload = {k: v for k, v in self.claims.items() if v is not None}
        if self.signing == "none":
            return f"{_b64({'alg': 'none', 'typ': 'JWT'})}.{_b64(payload)}."
        private = _OTHER_PRIVATE if self.signing == "other_key" else _GOOGLE_PRIVATE
        signer = crypt.RSASigner.from_string(private, key_id=KEY_ID)
        return google_jwt.encode(signer, payload).decode()

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("Google is down", request=request)
        url = str(request.url)
        if request.method == "POST" and url == TOKEN_ENDPOINT:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error})
            self.issued_id_tokens.append(self.id_token())
            return httpx.Response(
                200,
                json={
                    "access_token": "ya29.fake-access-token",
                    "expires_in": 3599,
                    "scope": "openid https://www.googleapis.com/auth/userinfo.email",
                    "token_type": "Bearer",
                    "id_token": self.issued_id_tokens[-1],
                },
            )
        if request.method == "GET" and url == CERTS_URL:
            self.cert_fetches += 1
            headers = {"cache-control": self.cache_control} if self.cache_control else {}
            return httpx.Response(200, json={KEY_ID: _GOOGLE_PUBLIC}, headers=headers)
        return httpx.Response(404)

    def http(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))
