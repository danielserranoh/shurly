"""
Phase 6.4 — browser errors reach the logs (for the dogfood's signal, ROADMAP 5.6.1).

The web app reports what breaks in a person's browser: an uncaught error, a rejected promise, or a
Content-Security-Policy or Trusted Types block, which a `<meta>` policy can't report by itself. Each
report becomes one `client.error` line in the event log, next to the API's `http.request` lines, so
the same metric filter and Logs Insights queries see both (DEPLOYMENT.md § Error alerting).

Anyone may report: a signed-out page like /login/ can break too. Limited per client IP
(`RATE_LIMIT_CLIENT_ERRORS_PER_IP`, server/utils/rate_limit.py). The line never carries the IP, a
query string or a fragment; the account's id only when the report came with a token that checks out.
The event log is JSON, one object per line: a newline inside a message is escaped, so a report
can't forge a line.
"""

import re
from typing import Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field, field_validator

from server.core.auth import get_optional_user
from server.core.models import User
from server.utils.event_log import log_event

client_errors_router = APIRouter()

# A URL's query and fragment, up to where the URL ends in running text.
_URL_TAIL = re.compile(r"(https?://[^\s?#]+)[?#][^\s,;)\]'\"]*")


def _without_url_tails(text: str) -> str:
    return _URL_TAIL.sub(r"\1", text)


def _before_query(text: str) -> str:
    return re.split(r"[?#]", text, maxsplit=1)[0]


class ClientErrorReport(BaseModel):
    """What the web app sends: never form values, storage, or the page's query."""

    kind: Literal["error", "rejection", "csp"] = Field(
        description="An uncaught error, a rejected promise, or a CSP or Trusted Types block"
    )
    message: str = Field(min_length=1, max_length=500)
    source: str = Field("", max_length=300, description="The script and where in it: file:line:col")
    page: str = Field(max_length=300, description="The page's path")

    @field_validator("page")
    @classmethod
    def a_path(cls, page: str) -> str:
        if not page.startswith("/") or page.startswith("//"):
            raise ValueError("the page's path, from its first /")
        return _before_query(page)

    @field_validator("source")
    @classmethod
    def no_query(cls, source: str) -> str:
        return _before_query(source)

    @field_validator("message")
    @classmethod
    def no_url_tails(cls, message: str) -> str:
        return _without_url_tails(message)


@client_errors_router.post(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Logged"},
        422: {"description": "Not a report"},
        429: {"description": "Too many"},
    },
)
def report_client_error(
    report: ClientErrorReport, account: User | None = Depends(get_optional_user)
):
    """Log a browser's error report as a `client.error` line. Anyone may call it; limited per IP."""
    fields = report.model_dump()
    if account is not None:
        fields["user_id"] = str(account.id)
    log_event("client.error", **fields)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
