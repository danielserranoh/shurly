"""
Phase 10.2 — what a service token may do, and from where (`_pm/spec_service_accounts.md` § v2).

Checked where the token authenticates (`get_service_token`, server/core/auth.py), on every REST
request that carries one. The MCP refuses service tokens before any of this.

- **Allowed IP ranges.** A token with `allowed_ip_ranges` works only from an address in one of
  them (IPv4 or IPv6 CIDRs), as `client_ip` sees it: CloudFront's viewer, or past
  TRUSTED_PROXIES. Empty or NULL, any address. Elsewhere, a 403 (`ip_not_allowed`); the
  address is never logged nor shown.
- **Scopes.** Each `/api/v1` route a service may call is in `SCOPE_FOR`, by method and the path
  as FastAPI declares it, with the scope it needs, or in `ANY_TOKEN`, which needs none. Any
  other route is refused to service tokens with a 403 (`service_account_not_allowed`), the
  answer v1 already gave on the routes only people use. A token without the scope gets a 403
  (`scope_missing`) naming it.
- **Acting on behalf of a person** (`X-Shurly-On-Behalf-Of`) needs `act_on_behalf`, on any
  route. A blank header names nobody (`acting_for`), so it needs nothing.

`NOT_FOR_SERVICES` and `PUBLIC` list the rest of `/api/v1`, so a test (tests/
test_phase102_token_enforcement.py) can walk every route: a new one has to be put somewhere.

v1's tokens all have every scope (migration 0019), so every route a v1 token could use, it
still can.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Iterator
from weakref import WeakKeyDictionary

from fastapi.routing import APIRoute
from starlette.requests import Request

from server.core.models import ServiceToken
from server.core.models.service_token import SERVICE_SCOPES
from server.utils.errors import SERVICE_ACCOUNT_NOT_ALLOWED, CodedHTTPException
from server.utils.event_log import log_event
from server.utils.network import client_ip
from server.utils.service_accounts import ON_BEHALF_HEADER

# The errors' stable codes (server/utils/errors.py has the others).
SCOPE_MISSING = "scope_missing"
IP_NOT_ALLOWED = "ip_not_allowed"

URLS_READ = "urls:read"
URLS_WRITE = "urls:write"
URLS_DELETE = "urls:delete"
TAGS_WRITE = "tags:write"
ANALYTICS_READ = "analytics:read"
ACT_ON_BEHALF = "act_on_behalf"
# The scopes a token can be given (`SERVICE_SCOPES`, the model's); the test checks they match.
SCOPES = SERVICE_SCOPES

_API = "/api/v1"
_URL = f"{_API}/urls/{{short_code}}"
_RULE = f"{_URL}/rules/{{rule_id}}"
_CAMPAIGN = f"{_API}/campaigns/{{campaign_id}}"
_TAG = f"{_API}/tags/{{tag_id}}"
_URL_STATS = f"{_API}/analytics/urls/{{short_code}}"
_CAMPAIGN_STATS = f"{_API}/analytics/campaigns/{{campaign_id}}"

# Method and route → the scope a service token needs. Campaigns and redirect rules are `urls:*`.
SCOPE_FOR: dict[tuple[str, str], str] = {
    # Reading links, their rules and previews, campaigns and tags.
    ("GET", f"{_API}/urls"): URLS_READ,
    ("GET", _URL): URLS_READ,
    ("GET", f"{_URL}/preview"): URLS_READ,
    ("GET", f"{_URL}/rules"): URLS_READ,
    ("GET", f"{_API}/campaigns"): URLS_READ,
    ("GET", _CAMPAIGN): URLS_READ,
    ("GET", f"{_CAMPAIGN}/export"): URLS_READ,
    ("GET", f"{_API}/tags"): URLS_READ,
    # Making and changing them.
    ("POST", f"{_API}/urls"): URLS_WRITE,
    ("POST", f"{_API}/urls/custom"): URLS_WRITE,
    ("POST", f"{_API}/urls/fetch-metadata"): URLS_WRITE,
    ("PATCH", _URL): URLS_WRITE,
    ("PATCH", f"{_URL}/tags"): URLS_WRITE,
    ("POST", f"{_API}/urls/bulk/tags"): URLS_WRITE,
    ("POST", f"{_URL}/refresh-preview"): URLS_WRITE,
    ("POST", f"{_URL}/rules"): URLS_WRITE,
    ("PATCH", _RULE): URLS_WRITE,
    ("POST", f"{_API}/campaigns"): URLS_WRITE,
    ("PATCH", f"{_CAMPAIGN}/tags"): URLS_WRITE,
    # Deleting them.
    ("DELETE", _URL): URLS_DELETE,
    ("DELETE", _RULE): URLS_DELETE,
    ("DELETE", _CAMPAIGN): URLS_DELETE,
    # The organization's tags.
    ("POST", f"{_API}/tags"): TAGS_WRITE,
    ("PATCH", _TAG): TAGS_WRITE,
    ("DELETE", _TAG): TAGS_WRITE,
    # Analytics.
    ("GET", f"{_URL_STATS}/daily"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/weekly"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/geo"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/totals"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/timeseries"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/breakdown"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/visits"): ANALYTICS_READ,
    ("GET", f"{_URL_STATS}/visits.csv"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/summary"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/users"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/totals"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/timeseries"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/breakdown"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/recipients"): ANALYTICS_READ,
    ("GET", f"{_CAMPAIGN_STATS}/recipients.csv"): ANALYTICS_READ,
    ("GET", f"{_API}/analytics/overview"): ANALYTICS_READ,
    ("GET", f"{_API}/analytics/orphan-visits"): ANALYTICS_READ,
    ("GET", f"{_API}/analytics/orphan-visits/grouped"): ANALYTICS_READ,
    # The organization's people, by email: whom the service may name in X-Shurly-On-Behalf-Of.
    # v1 let every token read it; now the tokens that act for people do.
    ("GET", f"{_API}/organization/members"): ACT_ON_BEHALF,
}

# Routes any service token may call, whatever its scopes: who it is, its organization, and its
# own account (v1 let every token call them, and they touch nothing but the account itself).
ANY_TOKEN: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{_API}/auth/me"),
        ("PATCH", f"{_API}/auth/me/profile"),
        ("PUT", f"{_API}/auth/me/avatar"),
        ("GET", f"{_API}/auth/me/avatar"),
        ("DELETE", f"{_API}/auth/me/avatar"),
        ("DELETE", f"{_API}/auth/api-key"),  # it has none: nothing to revoke
        ("GET", f"{_API}/organization"),
        ("GET", f"{_API}/organization/logo"),
        ("POST", f"{_API}/client-errors"),  # anyone may report one, signed in or not
    }
)

# Routes for people only. v1 refused them to service tokens already, in the route.
NOT_FOR_SERVICES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", f"{_API}/auth/change-password"),
        ("PUT", f"{_API}/auth/password"),
        ("DELETE", f"{_API}/auth/password"),
        ("POST", f"{_API}/auth/api-key/generate"),
        ("PUT", f"{_API}/organization/logo"),
        ("DELETE", f"{_API}/organization/logo"),
        ("PATCH", f"{_API}/organization/members/{{user_id}}"),
        ("DELETE", f"{_API}/organization/members/{{user_id}}"),
        ("POST", f"{_API}/organization/transfer-ownership"),
        ("GET", f"{_API}/organization/removed-members"),
        ("POST", f"{_API}/organization/adopt-personal-links"),
        ("GET", f"{_API}/waitlist"),
        ("GET", f"{_API}/waitlist/export"),
        ("DELETE", f"{_API}/waitlist/{{entry_id}}"),
    }
)
# And everything under these: managing service accounts is for a person signed in.
NOT_FOR_SERVICES_UNDER: tuple[str, ...] = (f"{_API}/service-accounts",)

# Routes that never read a token: a service calls them as anyone does.
PUBLIC: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", f"{_API}/health"),
        ("GET", f"{_API}/health/db"),
        ("POST", f"{_API}/auth/register"),
        ("POST", f"{_API}/auth/login"),
        ("GET", f"{_API}/auth/google/start"),
        ("GET", f"{_API}/auth/google/callback"),
        ("POST", f"{_API}/auth/google/exchange"),
        ("POST", f"{_API}/waitlist"),
    }
)


def not_for_services(method: str, path: str) -> bool:
    return (method, path) in NOT_FOR_SERVICES or any(
        path == prefix or path.startswith(prefix + "/") for prefix in NOT_FOR_SERVICES_UNDER
    )


# ---------------------------------------------------------------- The route a request reached


def api_routes(routes, prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """(the path as declared, with its routers' prefixes; the route) for every APIRoute, into
    the routers FastAPI includes lazily (0.141 and later)."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from api_routes(included.routes, prefix + (route.include_context.prefix or ""))
        elif isinstance(route, APIRoute):
            yield prefix + route.path, route


# app → {id(route): its full path}. `request.scope["route"]` is the route as its router
# declares it, without the prefixes it was included under.
_PATHS: WeakKeyDictionary = WeakKeyDictionary()


def _full_path(app, route: APIRoute) -> str | None:
    paths = _PATHS.get(app)
    if paths is None or id(route) not in paths:  # first use, or routes added since
        paths = {id(found): path for path, found in api_routes(app.routes)}
        _PATHS[app] = paths
    return paths.get(id(route))


def route_of(request: Request) -> tuple[str, str | None]:
    """The request's method (HEAD as GET) and its route's path template, or None outside one."""
    method = "GET" if request.method == "HEAD" else request.method
    route = request.scope.get("route")
    if not isinstance(route, APIRoute):
        return method, None
    return method, _full_path(request.app, route)


# ---------------------------------------------------------------- The checks


def address_allowed(address: str, ranges: Iterable[str] | None) -> bool:
    """Whether `address` falls in one of `ranges` (CIDRs, IPv4 or IPv6). No ranges, any
    address. An IPv4 address seen as IPv6 (`::ffff:198.51.100.7`) is matched as IPv4 too."""
    ranges = list(ranges or [])
    if not ranges:
        return True
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    candidates = [ip]
    if ip.version == 6 and ip.ipv4_mapped is not None:
        candidates.append(ip.ipv4_mapped)
    for cidr in ranges:
        try:
            network = ipaddress.ip_network(str(cidr).strip(), strict=False)
        except ValueError:
            continue
        if any(candidate in network for candidate in candidates):
            return True
    return False


def _refused(token: ServiceToken, reason: str, **fields) -> None:
    log_event(
        "service_token.refused",
        service_account_id=str(token.service_account_id),
        token_id=str(token.id),
        reason=reason,
        **fields,
    )


def ensure_address_allowed(request: Request, token: ServiceToken) -> None:
    """403 when the token has allowed ranges and the request comes from outside them."""
    if address_allowed(client_ip(request), token.allowed_ip_ranges):
        return
    _refused(token, "address")  # never the address
    raise CodedHTTPException(
        403, IP_NOT_ALLOWED, "This service token can't be used from this address."
    )


def _missing(token: ServiceToken, scope: str, method: str, path: str) -> CodedHTTPException:
    _refused(token, "scope", scope=scope, method=method, route=path)
    return CodedHTTPException(
        403, SCOPE_MISSING, f"This service token doesn't have the `{scope}` scope."
    )


def ensure_allowed(request: Request, token: ServiceToken) -> None:
    """403 unless the token's scopes let it call the route, and name a person if it does."""
    method, path = route_of(request)
    scopes = set(token.scopes or [])
    if path is not None and (method, path) in ANY_TOKEN:
        needed = None
    elif path is not None and (method, path) in SCOPE_FOR:
        needed = SCOPE_FOR[(method, path)]
    else:
        _refused(token, "route", method=method, route=path)
        raise CodedHTTPException(
            403, SERVICE_ACCOUNT_NOT_ALLOWED, "A service account's token can't do this."
        )
    if needed is not None and needed not in scopes:
        raise _missing(token, needed, method, path)
    named = request.headers.get(ON_BEHALF_HEADER)
    if named is not None and named.strip() and ACT_ON_BEHALF not in scopes:
        raise _missing(token, ACT_ON_BEHALF, method, path)
