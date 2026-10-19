"""
Phase 10.1 — errors with a stable `code` for clients to act on.

Every error keeps `{"detail": "…"}`, the message for people. The cases an integration has to
tell apart add a `code` beside it, which never changes wording:

- `on_behalf_of_unknown` (422): `X-Shurly-On-Behalf-Of` names nobody in the service account's
  organization;
- `on_behalf_of_not_allowed` (403): the header, from a person's API key or session;
- `service_account_not_allowed` (403): a service account where only a person may act (setting a
  password, generating an API key, managing service accounts or the organization), or a route a
  service token may never call (Phase 10.2, server/utils/service_scopes.py);
- `scope_missing` (403, Phase 10.2): the service token lacks the scope the route needs, or
  `act_on_behalf` to send `X-Shurly-On-Behalf-Of`; the message names the scope;
- `ip_not_allowed` (403, Phase 10.2): the service token has allowed IP ranges, and the request
  came from outside them;
- `managed_link_protected` (403, Phase 10.3): a person changing or deleting a link a service
  account manages (server/utils/managed.py); the message names the integration to use instead.
  The managing service account never gets it: it changes its links as before.

The two 10.2 codes are defined in server/utils/service_scopes.py, beside the checks.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

ON_BEHALF_OF_UNKNOWN = "on_behalf_of_unknown"
ON_BEHALF_OF_NOT_ALLOWED = "on_behalf_of_not_allowed"
SERVICE_ACCOUNT_NOT_ALLOWED = "service_account_not_allowed"
MANAGED_LINK_PROTECTED = "managed_link_protected"


class CodedHTTPException(HTTPException):
    """An HTTPException answered as `{"detail": …, "code": …}`."""

    def __init__(self, status_code: int, code: str, detail: str, headers: dict | None = None):
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


async def coded_http_exception_handler(_request: Request, exc: CodedHTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
        headers=exc.headers,
    )


def service_account_not_allowed(detail: str = "A service account can't do this.") -> HTTPException:
    return CodedHTTPException(403, SERVICE_ACCOUNT_NOT_ALLOWED, detail)
