"""
Phase 5.8 — the MCP sign-in's pages in Shurly's brand.

fastmcp's OAuth proxy renders its own pages, with FastMCP's name and a logo loaded from
gofastmcp.com, and has no supported way to change them:
- the consent page (GET /mcp/consent), from `create_consent_html`;
- its errors, bare "<h1>Error</h1><p>…</p>" strings sent by `create_secure_html_response`;
- the errors after Google (GET /mcp/auth/callback), from `create_error_html`;
- "not registered" (GET /mcp/authorize with an unknown client), from
  `create_unregistered_client_html`.

`brand_fastmcp_pages` points fastmcp's names for those four at the functions below, which render
server/templates/mcp_consent.html and mcp_error.html. Everything else stays fastmcp's: the CSRF
token, the cookies, the redirect checks, the flow. `PageHeaders` gives every HTML page under /mcp
its headers.

An error page shows a `reason` from a fixed set, never text from the request: fastmcp's callback
page put the URL's error_description on screen, so a crafted link could show anyone's words under
our domain. What happened is logged (`mcp.sign_in_error`), never a token or a code.

Checked against fastmcp 4.0.6 to 4.0.10, whose four page modules are identical. A version that
renames or moves one of these names fails at import (`check_fastmcp`), so the pages can't fall
back to FastMCP's without anyone noticing.
"""

import base64
import hashlib
import importlib
import re
from importlib.metadata import version
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.datastructures import MutableHeaders
from starlette.responses import HTMLResponse

from server.core.config import settings
from server.utils.event_log import log_event

CONSENT_PAGE = "mcp_consent.html"
ERROR_PAGE = "mcp_error.html"
_TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "server" / "templates"),
    autoescape=select_autoescape(["html"]),
)

# What an error page can say, whatever fastmcp's reason for it. The copy is the template's.
REASONS = frozenset(
    {
        "expired",  # the sign-in is unknown or over its 15 minutes, or there's none at all
        "expired_page",  # the consent page is over its 15 minutes, or was answered already
        "other_browser",  # continued in another browser than the one that approved it
        "redirect_not_allowed",  # the client's callback isn't one MCP_OAUTH_ALLOWED_REDIRECT_URIS allows
        "cancelled",  # the person cancelled at Google
        "google_error",  # Google didn't finish the sign-in
        "unregistered",  # the client isn't registered (any more)
        "failed",  # anything else
    }
)

# fastmcp's consent errors (consent.py), by their message.
_CONSENT_ERRORS = {
    "Invalid or expired transaction": "expired",
    "Invalid redirect URI": "redirect_not_allowed",
    "Invalid or expired consent token": "expired_page",
    "Authorization session mismatch. Please try authenticating again.": "other_browser",
    "Invalid action": "failed",
}
# And the callback's (proxy.py, `_handle_idp_callback`).
_CALLBACK_ERRORS = {
    "Missing authorization code or transaction ID from the identity provider.": "google_error",
    "Invalid redirect URI": "redirect_not_allowed",
    "Invalid or expired authorization transaction. Please try authenticating again.": "expired",
    "Invalid authorization flow. Please try authenticating again.": "failed",
    "Authorization session mismatch. This can happen if you followed a link from another "
    "person or your session expired. Please try authenticating again.": "other_browser",
    "Internal server error during OAuth callback processing. Please try again.": "failed",
}
_GOOGLE_FAILED = "Authentication failed: "  # then the URL's error_description: never shown
_EXCHANGE_FAILED = "Token exchange with identity provider failed: "  # then the exception
_BARE_ERROR = re.compile(r"<h1>Error</h1><p>(?P<message>.*)</p>", re.S)
_ERROR_CODE = re.compile(r"[a-z_]{1,40}")  # OAuth's error codes: invalid_request, access_denied…
# Tokens, codes and URLs: anything long without spaces goes out of a log line.
_SECRET_LIKE = re.compile(r"\S{16,}")
_MARKER = "data-shurly-page="


def _scrubbed(text: str) -> str:
    return _SECRET_LIKE.sub("[redacted]", text)[:200]


def _logged(page: str, reason: str, **extra: str | None) -> None:
    fields = {name: value for name, value in extra.items() if value is not None}
    log_event("mcp.sign_in_error", page=page, reason=reason, **fields)


def _manual_url() -> str:
    base = (settings.frontend_url or "").rstrip("/")
    return f"{base}/manual/install-mcp/"


def consent_page(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    txn_id: str,
    csrf_token: str,
    client_name: str | None = None,
    is_cimd_client: bool = False,
    cimd_domain: str | None = None,
    **fastmcps_branding,
) -> str:
    """fastmcp's `create_consent_html`, with the same arguments. Its title, server name, icon,
    website and CSP (`fastmcps_branding`) are left out: the page is Shurly's, and PageHeaders
    sets the CSP."""
    return _TEMPLATES.get_template(CONSENT_PAGE).render(
        client_name=client_name or client_id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=list(scopes or []),
        verified_domain=cimd_domain if is_cimd_client else None,
        txn_id=txn_id,
        csrf_token=csrf_token,
        manual_url=_manual_url(),
    )


def error_page(reason: str, details: dict[str, str] | None = None) -> str:
    return _TEMPLATES.get_template(ERROR_PAGE).render(
        reason=reason if reason in REASONS else "failed", details=details
    )


def callback_error_page(
    error_title: str,
    error_message: str,
    error_details: dict[str, str] | None = None,
    **fastmcps_branding,
) -> str:
    """fastmcp's `create_error_html`, which only the callback after Google calls."""
    details = None
    if error_message.startswith(_GOOGLE_FAILED):
        code = (error_details or {}).get("Error Code", "")
        known = code if _ERROR_CODE.fullmatch(code) else None
        reason = "cancelled" if known == "access_denied" else "google_error"
        if reason == "google_error" and known:
            details = {"Error code": known}
        _logged("callback", reason, google_error=known)
    elif error_message.startswith(_EXCHANGE_FAILED):
        reason = "failed"
        # fastmcp logs the exception itself; this line says only that it happened, scrubbed.
        detail = _scrubbed(error_message.removeprefix(_EXCHANGE_FAILED))
        _logged("callback", "token_exchange", detail=detail)
    else:
        reason = _CALLBACK_ERRORS.get(error_message, "failed")
        unknown = None if error_message in _CALLBACK_ERRORS else _scrubbed(error_message)
        _logged("callback", reason, unknown=unknown)
    return error_page(reason, details)


def unregistered_page(client_id: str, *args, **fastmcps_branding) -> str:
    """fastmcp's `create_unregistered_client_html`. The client id, from the URL, isn't shown."""
    _logged("authorize", "unregistered")
    return error_page("unregistered")


def html_response(html: str, status_code: int = 200) -> HTMLResponse:
    """fastmcp's `create_secure_html_response`, in consent.py and authorize.py. Our pages go
    through as they are; fastmcp's bare errors become ours."""
    bare = _BARE_ERROR.fullmatch(html.strip())
    if bare:
        message = bare["message"]
        reason = _CONSENT_ERRORS.get(message, "failed")
        unknown = None if message in _CONSENT_ERRORS else _scrubbed(message)
        _logged("consent", reason, unknown=unknown)
        html = error_page(reason)
    elif _MARKER not in html:
        # A page of fastmcp's that isn't known here: it goes out, unstyled under our CSP.
        log_event("mcp.sign_in_page_unbranded", status=status_code)
    return HTMLResponse(content=html, status_code=status_code, headers={"X-Frame-Options": "DENY"})


# fastmcp's name for each renderer, where it calls it: the module that uses it, not the one
# defining it, since each imports the function into its own namespace.
_SWAPS = (
    ("fastmcp.server.auth.oauth_proxy.consent", "create_consent_html", consent_page),
    ("fastmcp.server.auth.oauth_proxy.proxy", "create_error_html", callback_error_page),
    (
        "fastmcp.server.auth.handlers.authorize",
        "create_unregistered_client_html",
        unregistered_page,
    ),
    ("fastmcp.server.auth.oauth_proxy.consent", "create_secure_html_response", html_response),
    ("fastmcp.server.auth.handlers.authorize", "create_secure_html_response", html_response),
)


def check_fastmcp() -> None:
    """Fail when fastmcp no longer has a name `brand_fastmcp_pages` swaps."""
    missing = []
    for module_name, name, _ in _SWAPS:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            missing.append(f"{module_name} (the module)")
            continue
        if not hasattr(module, name):
            missing.append(f"{module_name}.{name}")
    if missing:
        raise RuntimeError(
            f"fastmcp {version('fastmcp')} no longer has {', '.join(missing)}: the MCP sign-in "
            "would show FastMCP's pages. Update mcp_server/pages.py for this version."
        )


def brand_fastmcp_pages() -> None:
    """Point fastmcp's page renderers at Shurly's. Idempotent."""
    for module_name, name, ours in _SWAPS:
        setattr(importlib.import_module(module_name), name, ours)


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------


# Enough for either template to render; their <style> blocks have no Jinja, so any render gives
# the block that's served. Rendered, not read from the file: a comment can mention "<style>".
_SAMPLE = {
    "client_name": "",
    "client_id": "",
    "redirect_uri": "",
    "scopes": [],
    "verified_domain": None,
    "txn_id": "",
    "csrf_token": "",
    "manual_url": "",
    "reason": "failed",
    "details": None,
}


def style_hash(template: str) -> str:
    """The CSP hash of a template's one <style> block, as it's served."""
    served = _TEMPLATES.get_template(template).render(**_SAMPLE)
    style = re.search(r"<style>(.*?)</style>", served, re.S).group(1)
    return "sha256-" + base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()


_STYLES = " ".join(dict.fromkeys(f"'{style_hash(t)}'" for t in (CONSENT_PAGE, ERROR_PAGE)))
PAGE_HEADERS = {
    # No form-action: Chrome applies it along the whole redirect chain after the consent form,
    # to Google, back to /mcp/auth/callback, then to the client's callback (claude.ai, or
    # http://localhost, or a claude:// app link). fastmcp leaves it out for the same reason
    # (oauth_proxy/ui.py); DEPLOYMENT.md § The MCP's sign-in pages.
    "Content-Security-Policy": (
        f"default-src 'none'; style-src {_STYLES}; img-src data:; base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",  # the consent page carries a CSRF token
    "Referrer-Policy": "no-referrer",  # its address carries the sign-in's txn_id
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex",
}


class PageHeaders:
    """PAGE_HEADERS on every HTML response of the app it wraps (the /mcp mount, main.py).
    Everything else, the MCP's JSON and its event streams, goes through untouched."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith("text/html"):
                    for name, value in PAGE_HEADERS.items():
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


check_fastmcp()
