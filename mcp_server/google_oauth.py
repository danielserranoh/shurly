"""
Phase 5.8 — MCP clients sign in with Google, through fastmcp's OAuth proxy, and
land on the same Shurly account as on the web.

fastmcp's GoogleProvider runs the OAuth 2.1 side: client registration (DCR, and
Client ID Metadata Documents), its consent page, Google, the code exchange. It
issues its own tokens, each standing for a Google token it keeps in the database
(mcp_server/oauth_store.py). This subclass adds Shurly's side:

- Signing in, when the client redeems its code: Google's ID token is checked by
  `verify_id_token` (server/utils/google_oidc.py: signature, aud, iss, exp,
  email_verified, hd) and the account comes from `sign_in_with_google`
  (server/utils/google_sign_in.py). Those are the web's rules: the domain gate and
  the membership, account_conflict, closed accounts, the pre-hijack lockout. A
  refusal means no token (invalid_grant).
- Refreshing: the account is found by Google's `sub`. A closed one gets nothing
  more, so the Google tokens stored for it can't be used again through us.
- Every request: fastmcp checks the Google token with Google (tokeninfo and
  userinfo). A success is kept for 60 seconds, so a suspension at Google takes up
  to a minute to bite. The account is looked up on every request, so closing it
  in Shurly bites at once. The claims have ShurlyTokenVerifier's shape, so the
  tools don't care how the caller signed in; `forward_bearer_auth` gives the API a
  short-lived JWT instead of the proxy's token (mcp_server/auth.py).
"""

import hashlib
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

import anyio.to_thread
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.jwt_issuer import derive_jwt_key
from fastmcp.server.auth.providers.google import GoogleProvider, GoogleTokenVerifier
from mcp.server.auth.provider import TokenError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from mcp_server.oauth_store import encrypted_database_store
from server.core.config import settings
from server.core.models import UserIdentity
from server.utils.event_log import log_event
from server.utils.google_oidc import GoogleHttp, GoogleSignInError, verify_id_token
from server.utils.google_sign_in import PROVIDER, sign_in_with_google

GOOGLE_SCOPES = ["openid", "email"]
_VERIFIED_FOR = 60  # seconds a successful check with Google is kept
_VERIFIED_MAX = 1024  # tokens kept at most

# Set while the client redeems its authorization code, i.e. while signing in;
# unset while refreshing. fastmcp calls the same hook for both.
_SIGNING_IN: ContextVar[bool] = ContextVar("shurly_mcp_signing_in", default=False)

_REFUSED = {
    "invalid_token": "Google's answer didn't check out.",
    "domain": "Only accounts of the organization's Google Workspace can use Shurly.",
    "unverified": "Google hasn't verified this account's address.",
    "inactive": "This Shurly account is closed.",
    "account_conflict": "This address's Shurly account belongs to another Google account.",
    "google_unavailable": "Google couldn't be reached. Try again.",
    "try_again": "Try again.",
}


@dataclass(frozen=True)
class _Account:
    id: UUID
    email: str


@dataclass(frozen=True)
class _Verified:
    until: float  # time.monotonic()
    subject: str  # Google's `sub`
    scopes: tuple[str, ...]
    expires_at: int | None


class _VerifiedTokens:
    """Successful checks with Google, by a hash of the token: at most 60 s, bounded."""

    def __init__(self):
        self._entries: OrderedDict[str, _Verified] = OrderedDict()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> _Verified | None:
        key = self._key(token)
        entry = self._entries.get(key)
        if entry is None or entry.until <= time.monotonic():
            self._entries.pop(key, None)
            return None
        return entry

    def put(self, token: str, verified: AccessToken, subject: str) -> _Verified:
        until = time.monotonic() + _VERIFIED_FOR
        if verified.expires_at is not None:
            until = min(until, time.monotonic() + verified.expires_at - time.time())
        entry = _Verified(until, subject, tuple(verified.scopes), verified.expires_at)
        self._entries[self._key(token)] = entry
        while len(self._entries) > _VERIFIED_MAX:
            self._entries.popitem(last=False)
        return entry


class ShurlyGoogleProvider(GoogleProvider):
    """fastmcp's Google OAuth proxy, mapping each Google identity to its Shurly account."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker,
        hosted_domain: str,
        google_http: GoogleHttp | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._session_factory = session_factory
        self._client_id = kwargs["client_id"]
        self._hosted_domain = hosted_domain
        self._google_http = google_http or GoogleHttp()
        # Our own handle on fastmcp's check with Google, for refreshes.
        self._google_check = GoogleTokenVerifier(
            required_scopes=GOOGLE_SCOPES,
            http_client=kwargs.get("http_client"),
            audience=kwargs["client_id"],
        )
        self._verified = _VerifiedTokens()

    async def exchange_authorization_code(self, client, authorization_code):
        signing_in = _SIGNING_IN.set(True)
        try:
            return await super().exchange_authorization_code(client, authorization_code)
        finally:
            _SIGNING_IN.reset(signing_in)

    async def _extract_upstream_claims(self, idp_tokens: dict) -> None:
        """Sign in (code exchange) or check the account again (refresh); refuse with no token.

        Nothing goes into the proxy's JWT: requests find the account by `sub`.
        """
        if _SIGNING_IN.get():
            await anyio.to_thread.run_sync(self._sign_in, idp_tokens.get("id_token"))
            return None
        checked = await self._google_check.verify_token(idp_tokens.get("access_token") or "")
        subject = checked.claims.get("sub") if checked and checked.claims else None
        account = await anyio.to_thread.run_sync(self._active_account, subject)
        if account is None:
            reason = "inactive" if subject else "invalid_token"
            log_event("auth.google_refused", reason=reason, surface="mcp", on="refresh")
            raise TokenError("invalid_grant", _REFUSED[reason])
        return None

    def _sign_in(self, id_token: str | None) -> None:
        try:
            if not id_token:
                raise GoogleSignInError("invalid_token")
            account = verify_id_token(
                id_token,
                client_id=self._client_id,
                hosted_domain=self._hosted_domain,
                http=self._google_http,
            )
            with self._session_factory() as db:
                try:
                    user = sign_in_with_google(db, account)
                    db.commit()
                except IntegrityError:
                    # Two first sign-ins of the same person crossed.
                    db.rollback()
                    raise GoogleSignInError("try_again") from None
                user_id = str(user.id)
        except GoogleSignInError as refused:
            log_event(
                "auth.google_refused", reason=refused.reason, surface="mcp", **refused.details
            )
            description = _REFUSED.get(refused.reason, _REFUSED["invalid_token"])
            raise TokenError("invalid_grant", description) from None
        log_event("auth.login", method="google", user_id=user_id, surface="mcp")

    def _active_account(self, subject: str | None) -> _Account | None:
        if not subject:
            return None
        with self._session_factory() as db:
            identity = (
                db.query(UserIdentity)
                .filter(UserIdentity.provider == PROVIDER, UserIdentity.subject == subject)
                .first()
            )
            if identity is None or not identity.user.is_active:
                return None
            return _Account(id=identity.user.id, email=identity.user.email)

    async def load_access_token(self, token: str) -> AccessToken | None:  # type: ignore[override]
        verified = self._verified.get(token)
        if verified is None:
            checked = await super().load_access_token(token)
            subject = checked.claims.get("sub") if checked and checked.claims else None
            if not subject:
                return None
            verified = self._verified.put(token, checked, subject)
        account = await anyio.to_thread.run_sync(self._active_account, verified.subject)
        if account is None:
            return None
        return AccessToken(
            token=token,
            client_id=str(account.id),
            scopes=list(verified.scopes),
            expires_at=verified.expires_at,
            # ShurlyTokenVerifier's shape, plus how the caller signed in.
            claims={
                "sub": account.email,
                "user_id": str(account.id),
                "scope": None,
                "auth_method": "google",
            },
        )


def build_google_provider(
    session_factory: sessionmaker | None = None,
    provider_class: type[ShurlyGoogleProvider] = ShurlyGoogleProvider,
    **overrides,
) -> ShurlyGoogleProvider:
    """The provider from settings (`settings.mcp_oauth_configured` must hold).

    Tests pass their session factory, and a fake Google through `provider_class`,
    `http_client` and `google_http`.
    """
    if session_factory is None:
        from server.core import SessionLocal as session_factory
    signing_key = settings.mcp_oauth_signing_key.get_secret_value()
    return provider_class(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        base_url=settings.mcp_public_url.rstrip("/"),
        required_scopes=GOOGLE_SCOPES,
        # Only the MCP clients we target can register (consent phishing otherwise).
        allowed_client_redirect_uris=list(settings.mcp_oauth_allowed_redirect_uris),
        client_storage=encrypted_database_store(session_factory, signing_key),
        # A key of its own, never the Google client secret: a leaked or rotated
        # Google secret must not forge or end every MCP token.
        jwt_signing_key=derive_jwt_key(
            high_entropy_material=signing_key, salt="shurly-mcp-oauth-signing"
        ),
        session_factory=session_factory,
        hosted_domain=settings.organization_domain.strip(),
        **overrides,
    )
