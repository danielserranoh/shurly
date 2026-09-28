"""
Phase 3.13.2 — the Google side of signing in: OpenID Connect, authorization code
flow with PKCE (S256), for a confidential client.

Google says who someone is; Shurly still issues its own JWT, so the API, the
dashboard and API keys don't care how anyone signed in. The account rules are in
`server/utils/google_sign_in.py`, the endpoints in `server/app/google_auth.py`.

The ID token comes straight from Google's token endpoint, never through the
browser. google-auth checks its signature against Google's certs, `aud` (our
client id), `iss` and `exp`, and accepts RS256 only. Then two checks of ours:
`email_verified`, and `hd` equal to the organization's domain. The `hd` sent to
Google only narrows its account chooser. No OIDC nonce: PKCE and the direct
token-endpoint fetch already stop code injection (RFC 9700).

Nothing here logs. Never log the client secret, the authorization code, the
PKCE verifier or the ID token.
"""

import base64
import hashlib
import re
import secrets
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlencode

import google.auth.transport
import httpx
from google.auth import exceptions as google_exceptions
from google.oauth2 import id_token as google_id_token

AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

_TIMEOUT = 10  # seconds, for each call to Google
_CLOCK_SKEW = 10  # seconds allowed between Google's clock and ours
_GOOGLE_ERROR = re.compile(r"^[a-z_]{1,64}$")
_MAX_AGE = re.compile(r"(?:^|[,\s])max-age=(\d+)")


class GoogleSignInError(Exception):
    """
    Why a sign-in failed. `reason` is the short code the frontend gets (see
    `server/app/google_auth.py`); `details` are extra fields for the log line,
    never personal data or secrets.
    """

    def __init__(self, reason: str, **details):
        super().__init__(reason)
        self.reason = reason
        self.details = details


@dataclass(frozen=True)
class GoogleAccount:
    """A Google account whose ID token checked out."""

    subject: str  # Google's `sub`: stays when the address changes
    email: str  # lowercase
    # Phase 3.12 — with the `profile` scope, for an empty profile. The MCP's sign-in
    # asks for `openid email` only, so it gets none.
    given_name: str | None = None
    family_name: str | None = None


def new_code_verifier() -> str:
    """A PKCE verifier: 86 characters from the unreserved set (RFC 7636 allows 43–128)."""
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for `verifier`: BASE64URL(SHA256(verifier)), unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class _CachedGets:
    """GET responses kept for as long as their Cache-Control `max-age` allows."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[float, _Response]] = {}

    def get(self, url: str) -> "_Response | None":
        with self._lock:
            entry = self._entries.get(url)
        if entry is None or time.monotonic() >= entry[0]:
            return None
        return entry[1]

    def put(self, url: str, response: "_Response", cache_control: str | None) -> None:
        directives = (cache_control or "").lower()
        match = _MAX_AGE.search(directives)
        if not match or "no-store" in directives or "no-cache" in directives:
            return
        with self._lock:
            self._entries[url] = (time.monotonic() + int(match.group(1)), response)


class GoogleHttp:
    """
    How Shurly reaches Google: one httpx client, and Google's signing certs kept as
    long as their Cache-Control allows (Google rotates them well within that).
    One per process; tests pass a client on a fake Google.
    """

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=_TIMEOUT)
        self.cached_gets = _CachedGets()


class _Response(google.auth.transport.Response):
    def __init__(self, status: int, headers: Mapping[str, str], data: bytes):
        self._status = status
        self._headers = headers
        self._data = data

    @property
    def status(self) -> int:
        return self._status

    @property
    def headers(self) -> Mapping[str, str]:
        return self._headers

    @property
    def data(self) -> bytes:
        return self._data


class _GoogleAuthRequest(google.auth.transport.Request):
    """google-auth's HTTP interface on our httpx client, which it uses to fetch the certs."""

    def __init__(self, http: GoogleHttp):
        self._http = http

    def __call__(self, url, method="GET", body=None, headers=None, timeout=None, **kwargs):
        if method == "GET":
            cached = self._http.cached_gets.get(url)
            if cached is not None:
                return cached
        try:
            response = self._http.client.request(
                method, url, content=body, headers=headers, timeout=timeout or _TIMEOUT
            )
        except httpx.HTTPError as exc:
            raise google_exceptions.TransportError(type(exc).__name__) from None
        result = _Response(response.status_code, dict(response.headers), response.content)
        if method == "GET" and response.status_code == 200:
            self._http.cached_gets.put(url, result, response.headers.get("cache-control"))
        return result


class GoogleOIDC:
    """Google's side of one sign-in, for our OAuth client."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        hosted_domain: str,
        http: GoogleHttp,
    ):
        # Without a client id google-auth skips the `aud` check; without a domain,
        # any Google account (Gmail included) would pass the `hd` one.
        if not client_id or not hosted_domain:
            raise ValueError("Google sign-in needs a client id and the organization's domain")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._hosted_domain = hosted_domain.lower()
        self._http = http

    def authorization_url(self, state: str, code_verifier: str) -> str:
        """Where to send the browser: Google's sign-in, for this `state` and PKCE verifier."""
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                # Phase 3.12: `profile` puts the names in the ID token, for the profile.
                "scope": "openid email profile",
                "state": state,
                "code_challenge": code_challenge(code_verifier),
                "code_challenge_method": "S256",
                # A hint for Google's account chooser only: the ID token's `hd` is checked.
                "hd": self._hosted_domain,
            }
        )
        return f"{AUTHORIZATION_ENDPOINT}?{query}"

    def account_for(self, code: str, code_verifier: str) -> GoogleAccount:
        """Redeem the authorization code for an ID token, and check it."""
        return self._verify(self._redeem(code, code_verifier))

    def _redeem(self, code: str, code_verifier: str) -> str:
        try:
            response = self._http.client.post(
                TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "code_verifier": code_verifier,
                    "redirect_uri": self._redirect_uri,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError:
            raise GoogleSignInError("google_unavailable") from None
        if response.status_code >= 500:
            raise GoogleSignInError("google_unavailable", google_status=response.status_code)
        if response.status_code != 200:
            # e.g. invalid_grant (a used or expired code), invalid_client (our secret).
            raise GoogleSignInError("invalid_token", google_error=_google_error(response))
        try:
            id_token = response.json()["id_token"]
        except (ValueError, KeyError, TypeError):
            raise GoogleSignInError("invalid_token") from None
        if not isinstance(id_token, str):
            raise GoogleSignInError("invalid_token")
        return id_token

    def _verify(self, id_token: str) -> GoogleAccount:
        return verify_id_token(
            id_token, client_id=self._client_id, hosted_domain=self._hosted_domain, http=self._http
        )


def verify_id_token(
    id_token: str, *, client_id: str, hosted_domain: str, http: GoogleHttp
) -> GoogleAccount:
    """
    The account behind a Google ID token, if it checks out: signature against
    Google's certs, `aud` (our client id), `iss` and `exp` (google-auth), then a
    verified address and `hd` equal to `hosted_domain`. Also used by the MCP's
    sign-in (mcp_server/google_oauth.py), so both apply the same checks.
    """
    # Without a client id google-auth skips the `aud` check; without a domain, any
    # Google account (Gmail included) would pass the `hd` one.
    if not client_id or not hosted_domain:
        raise ValueError("Checking an ID token needs a client id and the organization's domain")
    try:
        claims = google_id_token.verify_oauth2_token(
            id_token,
            _GoogleAuthRequest(http),
            audience=client_id,
            clock_skew_in_seconds=_CLOCK_SKEW,
        )
    except google_exceptions.TransportError:
        raise GoogleSignInError("google_unavailable") from None
    except (google_exceptions.GoogleAuthError, ValueError, KeyError):
        raise GoogleSignInError("invalid_token") from None

    if claims.get("email_verified") is not True:
        raise GoogleSignInError("unverified")
    if str(claims.get("hd") or "").lower() != hosted_domain.lower():
        raise GoogleSignInError("domain")
    subject, email = claims.get("sub"), claims.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str) or not email:
        raise GoogleSignInError("invalid_token")
    return GoogleAccount(
        subject=subject,
        email=email.lower(),
        given_name=_text(claims.get("given_name")),
        family_name=_text(claims.get("family_name")),
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _google_error(response: httpx.Response) -> str:
    """Google's error code (invalid_grant, …) for the log; nothing else from the body."""
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return "unknown"
    return error if isinstance(error, str) and _GOOGLE_ERROR.match(error) else "unknown"
