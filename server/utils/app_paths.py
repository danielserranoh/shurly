"""
Phase 8.4 — the paths the app serves itself, on its own host only (option A, 2026-10-02).

The MCP, its OAuth metadata and the API's docs live on the app's host, shurly.griddo.io
(`app_host`). Short domains reach the same service (the ALB's rule 12), and there `/mcp`,
`/docs` and `/redoc` are links like any code: the routes that serve them don't match, so the
path falls through to `/{short_code}`, with its redirect, visit, orphan visit or 404. Shlink's
go.griddo.io/mcp, out there with 41 visits, keeps working. Without an app host (local
development, tests), every host is the app's, as before.

The Host header decides. The ALB passes the original one, and CloudFront forwards the viewer's
for shurly.griddo.io (its origin request policy, DEPLOYMENT.md § The distribution).
X-Forwarded-Host isn't read: anyone can send it.
"""

from collections.abc import Callable, Iterable

from starlette.routing import BaseRoute, Match
from starlette.types import Scope

from server.utils.domain import serves_app_paths
from server.utils.url import RESERVED_SHORT_CODES

# First path segments the app serves itself, beyond the reserved codes: the OpenAPI document,
# and the OAuth metadata RFC 8414 and RFC 9728 put at the root.
_ALSO_THE_APPS = frozenset({"openapi.json", ".well-known"})


def is_app_path(path: str) -> bool:
    """A path the app serves itself, by its first segment: `/mcp…`, `/docs…`, `/redoc`,
    `/openapi.json`, `/.well-known/…`."""
    first = path.lstrip("/").split("/", 1)[0]
    return first in RESERVED_SHORT_CODES or first in _ALSO_THE_APPS


def on_the_app_host(scope: Scope) -> bool:
    """Whether a request is on the host the app serves its own paths on (`serves_app_paths`)."""
    host = next(
        (value.decode("latin-1") for name, value in scope["headers"] if name == b"host"), ""
    )
    return serves_app_paths(host)


def serve_on_the_app_host_only(routes: Iterable[BaseRoute]) -> None:
    """
    The app's own routes among `routes` (`is_app_path`) match on the app's host only. On another
    host they don't match, and the router goes on to the next route: `/{short_code}`, registered
    after them, gets the path. Each route keeps its type, so whatever lists the app's routes still
    finds it.
    """
    for route in routes:
        if is_app_path(getattr(route, "path", None) or ""):
            route.matches = _on_the_app_host_only(route.matches)


def _on_the_app_host_only(matches: Callable) -> Callable:
    def on_the_app_host_only(scope: Scope) -> tuple[Match, Scope]:
        match, child_scope = matches(scope)
        # The host only for a path that matched: every request asks each of these routes.
        if match is not Match.NONE and not on_the_app_host(scope):
            return Match.NONE, {}
        return match, child_scope

    return on_the_app_host_only
