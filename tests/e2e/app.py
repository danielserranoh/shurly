"""
Phase 6.1 — the API the end-to-end tests (frontend/e2e/) run against: the real
app on a real PostgreSQL, with two things swapped so a run stays on this machine:

- Google is the pytest suite's fake (tests/fake_google.py). Its sign-in page is
  GET /__e2e/google/authorize, which sends the browser straight back to the real
  callback with a code; the fake token endpoint redeems it for a real RS256 ID
  token for OWNER, the organization's first owner.
- Link previews: nothing is fetched, every link has an empty one.

Playwright starts it (frontend/playwright.config.ts); by hand:

    E2E=1 DB_HOST=localhost DB_NAME=shurly_e2e … uv run uvicorn tests.e2e.app:app --port 18000

It refuses to start without E2E=1 or on a database that isn't local (guard.py).
It lives here, never in main.py, and the image never copies tests/
(tests/test_e2e_guard.py).
"""

import os
import time
from urllib.parse import urlencode

from tests.e2e.guard import refuse_unless_local

refuse_unless_local()

from fastapi import HTTPException, Request  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from pydantic import SecretStr  # noqa: E402

import server.utils.google_oidc as google_oidc  # noqa: E402
from server.core.config import settings  # noqa: E402
from tests.fake_google import CLIENT_ID, CLIENT_SECRET, FakeGoogle  # noqa: E402

# As frontend/e2e/env.ts has them.
API_URL = os.environ.get("E2E_API_URL", "http://127.0.0.1:18000")
WEB_URL = os.environ.get("E2E_WEB_URL", "http://127.0.0.1:14321")
OWNER = "e2e.owner@griddo.io"

# Before main builds the app, which reads the CORS origins then.
settings.frontend_url = WEB_URL
settings.cors_origins = [WEB_URL]
settings.organization_domain = "griddo.io"
settings.bootstrap_owner_email = OWNER
settings.allow_password_signup = False
settings.google_client_id = CLIENT_ID
settings.google_client_secret = SecretStr(CLIENT_SECRET)
settings.google_redirect_uri = f"{API_URL}/api/v1/auth/google/callback"
google_oidc.AUTHORIZATION_ENDPOINT = f"{API_URL}/__e2e/google/authorize"

import server.app.urls as urls  # noqa: E402
from main import app  # noqa: E402
from server.app.google_auth import get_google_http  # noqa: E402
from server.utils.opengraph import OpenGraphMetadata  # noqa: E402

GOOGLE = FakeGoogle()
GOOGLE.claims.update(email=OWNER, sub="e2e-owner", hd="griddo.io")
_google_http = google_oidc.GoogleHttp(GOOGLE.http())
app.dependency_overrides[get_google_http] = lambda: _google_http


async def _no_preview(url: str, timeout: int = 5) -> OpenGraphMetadata:
    """The tests' destinations don't exist, and nothing leaves the machine."""
    return OpenGraphMetadata()


urls.fetch_opengraph_metadata = _no_preview


async def authorize(request: Request) -> RedirectResponse:
    """Google's sign-in page, signed in already: back to the callback, as Google would."""
    query = request.query_params
    if query.get("redirect_uri") != settings.google_redirect_uri or not query.get("state"):
        raise HTTPException(status_code=400, detail="Not the registered redirect_uri, or no state")
    now = int(time.time())
    GOOGLE.claims.update(iat=now, exp=now + 3600)
    answer = urlencode({"state": query["state"], "code": "fake-google-code"})
    return RedirectResponse(f"{settings.google_redirect_uri}?{answer}", status_code=302)


# Ahead of the short-link routes, like every route main.py registers.
app.add_api_route("/__e2e/google/authorize", authorize, methods=["GET"], include_in_schema=False)
app.router.routes.insert(0, app.router.routes.pop())
