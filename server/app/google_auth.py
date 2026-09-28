"""
Phase 3.13.2 — sign in with Google: the endpoints, and the contract with the
static frontend (3.13.5).

1. GET /api/v1/auth/google/start — the "Sign in with Google" button navigates
   here (a full page, and no `next` parameter: the frontend keeps its return path
   in sessionStorage). It redirects to Google with a `state`, a PKCE challenge
   and `hd`, and sets the `shurly_google_state` cookie (HttpOnly, Secure,
   SameSite=Lax, Path=/api/v1/auth/google, 10 minutes), so the sign-in completes
   only in the browser that started it.
2. GET /api/v1/auth/google/callback — Google sends the browser back here. It
   checks the state (the cookie, and the database: single use), redeems Google's
   code, checks the ID token and finds or makes the account, then redirects to
       {FRONTEND_URL}/login/#code=<one-time code>
   or, when anything fails, to
       {FRONTEND_URL}/login/#error=<reason>
   In the fragment, so neither reaches a server log or a Referer. The target comes
   only from FRONTEND_URL, never from the request.
3. POST /api/v1/auth/google/exchange {"code": "…"} — the page trades the code,
   once and within 60 seconds, for the same body as POST /api/v1/auth/login:
   {"access_token": "…", "token_type": "bearer"}. 400 if the code is unknown,
   used or expired, or its account was closed. The JWT never travels in a URL.

Error reasons in the fragment:
- state: the sign-in expired (10 minutes), was used already, or began in another browser
- denied: cancelled at Google
- domain: not an account of the organization's Google Workspace (ORGANIZATION_DOMAIN)
- unverified: Google hasn't verified the address
- account_conflict: the address's Shurly account is linked to another Google account
- inactive: the account was closed
- invalid_token: Google's answer didn't check out
- google_unavailable: Google can't be reached, or sign in with Google isn't
  configured on this server
- try_again: two sign-ins of the same person crossed; the second can just retry

Until sign in with Google is configured (`settings.google_sign_in_configured`),
/start and /callback redirect with error=google_unavailable, or answer 503 when
FRONTEND_URL isn't set either.

For the frontend's Settings → Account (3.13.3): GET /api/v1/auth/me says
`has_password` and `has_google`; PUT and DELETE /api/v1/auth/password are in
`server/app/auth.py`. Their 403 for a session older than 10 minutes has a
machine-readable detail: {"code": "reauth_required", "message": "…"}.

Event log: auth.login {method: "google", user_id} when the JWT is issued,
auth.google_refused {reason, …} for a refused callback, auth.identity_linked when
a sign-in links an account made before Google. Never an address, a token or a code.
"""

import functools
import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from server.core import get_db
from server.core.auth import create_access_token
from server.core.config import settings
from server.schemas.auth import GoogleCodeExchange, Token
from server.schemas.responses import get_responses
from server.utils.event_log import log_event
from server.utils.google_oidc import GoogleHttp, GoogleOIDC, GoogleSignInError
from server.utils.google_sign_in import (
    STATE_TTL,
    issue_login_code,
    redeem_login_code,
    sign_in_with_google,
    start_sign_in,
    take_code_verifier,
)

google_router = APIRouter()

STATE_COOKIE = "shurly_google_state"
_COOKIE_PATH = "/api/v1/auth/google"
_REDIRECT = {302: {"description": "Redirect to Google, or back to the frontend"}}


@functools.cache
def get_google_http() -> GoogleHttp:
    """One per process, so Google's signing certs stay cached. Tests override it."""
    return GoogleHttp()


def get_google(http: GoogleHttp = Depends(get_google_http)) -> GoogleOIDC | None:
    """Google's side of the sign-in; None until it's configured."""
    if not settings.google_sign_in_configured:
        return None
    return GoogleOIDC(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret.get_secret_value(),
        redirect_uri=settings.google_redirect_uri,
        hosted_domain=settings.organization_domain.strip(),
        http=http,
    )


def _to_frontend(**fragment: str) -> RedirectResponse:
    """The frontend's login page, with `fragment` after the #. Only ever FRONTEND_URL."""
    url = f"{settings.frontend_url.rstrip('/')}/login/#{urlencode(fragment)}"
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        STATE_COOKIE, path=_COOKIE_PATH, secure=True, httponly=True, samesite="lax"
    )
    return response


def _unavailable() -> RedirectResponse:
    """Not configured: say so on the frontend's page, or 503 when there's no frontend either."""
    if not settings.frontend_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign in with Google isn't configured on this server.",
        )
    return _to_frontend(error="google_unavailable")


@google_router.get("/start", responses={**_REDIRECT, **get_responses(503)})
def google_start(
    google: GoogleOIDC | None = Depends(get_google),
    db: Session = Depends(get_db),
):
    """Send the browser to Google to sign in (a full-page navigation, not an API call)."""
    if google is None:
        return _unavailable()
    state, code_verifier = start_sign_in(db)
    db.commit()
    response = RedirectResponse(
        google.authorization_url(state, code_verifier), status_code=status.HTTP_302_FOUND
    )
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        STATE_COOKIE,
        state,
        max_age=int(STATE_TTL.total_seconds()),
        path=_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return response


@google_router.get("/callback", responses={**_REDIRECT, **get_responses(503)})
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    google: GoogleOIDC | None = Depends(get_google),
    db: Session = Depends(get_db),
):
    """Where Google sends the browser back; redirects to the frontend with a one-time code."""
    if google is None:
        return _unavailable()
    try:
        code_verifier = _take_state(request, db, state)
        if error:
            raise GoogleSignInError("denied")
        if not code:
            raise GoogleSignInError("invalid_token")
        account = google.account_for(code, code_verifier)
        user = sign_in_with_google(db, account)
        login_code = issue_login_code(db, user)
        db.commit()
    except GoogleSignInError as refused:
        db.rollback()
        log_event("auth.google_refused", reason=refused.reason, **refused.details)
        return _to_frontend(error=refused.reason)
    except IntegrityError:
        # Two sign-ins of the same person crossed (the unique address or `sub`).
        db.rollback()
        log_event("auth.google_refused", reason="try_again")
        return _to_frontend(error="try_again")
    return _to_frontend(code=login_code)


def _take_state(request: Request, db: Session, state: str | None) -> str:
    """The PKCE verifier for `state`, if the state is this browser's, unused and fresh."""
    cookie = request.cookies.get(STATE_COOKIE)
    if not state or not cookie or not hmac.compare_digest(state.encode(), cookie.encode()):
        raise GoogleSignInError("state")
    code_verifier = take_code_verifier(db, state)
    db.commit()  # used up, even if the rest of the sign-in fails
    if code_verifier is None:
        raise GoogleSignInError("state")
    return code_verifier


@google_router.post(
    "/exchange",
    response_model=Token,
    responses={
        200: {"description": "The JWT, as POST /auth/login returns it"},
        **get_responses(400, 422),
    },
)
def google_exchange(body: GoogleCodeExchange, db: Session = Depends(get_db)):
    """Trade the one-time code from the callback's redirect for a JWT (once, within 60 s)."""
    user = redeem_login_code(db, body.code)
    db.commit()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired sign-in code"
        )
    access_token = create_access_token(data={"sub": user.email})
    log_event("auth.login", method="google", user_id=str(user.id))
    return {"access_token": access_token, "token_type": "bearer"}
