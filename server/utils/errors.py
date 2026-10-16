"""
Phase 10.1 — errors with a stable `code` for clients to act on.

Every error keeps `{"detail": "…"}`, the message for people. The cases an integration has to
tell apart add a `code` beside it, which never changes wording:

- `on_behalf_of_unknown` (422): `X-Shurly-On-Behalf-Of` names nobody in the service account's
  organization;
- `on_behalf_of_not_allowed` (403): the header, from a person's API key or session;
- `service_account_not_allowed` (403): a service account where only a person may act (setting a
  password, generating an API key, managing service accounts or the organization).
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

ON_BEHALF_OF_UNKNOWN = "on_behalf_of_unknown"
ON_BEHALF_OF_NOT_ALLOWED = "on_behalf_of_not_allowed"
SERVICE_ACCOUNT_NOT_ALLOWED = "service_account_not_allowed"


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
