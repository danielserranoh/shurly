"""Network address helpers — IP anonymization and proxy trust resolution."""

import hashlib
import hmac
import ipaddress
from collections.abc import Iterable

from pydantic import SecretStr
from starlette.requests import Request

from server.core.config import settings

# Phase 6.3 — the viewer's address, as CloudFront sends it to the origin.
VIEWER_ADDRESS_HEADER = "cloudfront-viewer-address"
# What a visit stores without an address: every visit imported from Shlink, which exposes
# none, and one whose address couldn't be read. It's no one in particular, so it never counts
# as a unique visitor (`_distinct_visitors`, server/app/analytics.py).
UNKNOWN_IP = "unknown"

# How `client_ip` found the address (`client_ip_and_source`): what each request's log line says,
# since the address itself is never logged. CloudFront's viewer header; X-Forwarded-For, from a
# trusted proxy; or the connection's peer.
CLOUDFRONT, FORWARDED_FOR, SOCKET = "cloudfront", "xff", "socket"


def anonymize_ip(addr: str | None) -> str | None:
    """
    Phase 3.9.5 — Truncate an IP for GDPR pseudonymization.

    IPv4 → /24 (zero the last octet); IPv6 → /64 (zero the host bits).
    Returns the input unchanged if it does not parse as an IP, so callers can
    pass through "unknown" sentinels without special-casing.
    """
    if not addr:
        return addr
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return addr
    if isinstance(ip, ipaddress.IPv4Address):
        net = ipaddress.ip_network(f"{ip}/24", strict=False)
        return str(net.network_address)
    net = ipaddress.ip_network(f"{ip}/64", strict=False)
    return str(net.network_address)


def _addr_in_any_cidr(addr: str, cidrs: Iterable[str]) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if ip in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolve_client_ip(
    socket_addr: str | None,
    forwarded_for: str | None,
    trusted_proxies: Iterable[str],
) -> str:
    """
    Phase 3.9.6 — Pick the client IP given a TRUSTED_PROXIES allowlist.

    `X-Forwarded-For` is read only when the request comes from a trusted proxy
    (never from arbitrary clients: they can spoof it), and then from the right.
    Each proxy appends the address it saw, so the first entry from the right that
    isn't a trusted proxy is the client. The left end is whatever the client sent:
    Phase 6.3 stopped trusting it, since rate limits key on this address.
    """
    return _resolve(socket_addr, forwarded_for, trusted_proxies)[0]


def _resolve(
    socket_addr: str | None, forwarded_for: str | None, trusted_proxies: Iterable[str]
) -> tuple[str, str]:
    """`resolve_client_ip`, and whether X-Forwarded-For or the socket gave it."""
    socket_addr = socket_addr or "unknown"
    trusted = list(trusted_proxies)
    if not forwarded_for or not trusted or not _addr_in_any_cidr(socket_addr, trusted):
        return socket_addr, SOCKET
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _addr_in_any_cidr(hop, trusted):
            return hop, FORWARDED_FOR
    return (hops[0], FORWARDED_FOR) if hops else (socket_addr, SOCKET)


def viewer_address(value: str | None) -> str | None:
    """
    Phase 6.3 — the IP in a `CloudFront-Viewer-Address` header, or None if it doesn't
    parse. The header is the address and the viewer's source port: `198.51.100.10:46532`,
    and an IPv6 address unbracketed, so the port follows the last colon
    (`2001:db8::1:46532`). A bracketed `[2001:db8::1]:46532` is read too.
    """
    if not value:
        return None
    host, colon, port = value.strip().rpartition(":")
    if not colon or not port.isdigit():
        return None
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _canonical_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def cloudfront_viewer(viewer_header: str | None, forwarded_for: str | None) -> str | None:
    """
    Phase 6.3 — the viewer's IP from `CloudFront-Viewer-Address`, if it's the address
    CloudFront appended to X-Forwarded-For: second from the right, since the ALB appends
    the edge after it ("append", its default X-Forwarded-For mode).

    CloudFront writes both from the same connection, so they differ only when one isn't
    CloudFront's: an origin request policy that doesn't add CloudFront's headers
    (AllViewer) forwards the viewer's own `CloudFront-Viewer-Address`, or the ALB stopped
    appending. Then None, and X-Forwarded-For decides. Compared in canonical form. It
    takes both going wrong at once to believe a forged address: with the ALB not
    appending, the entry second from the right can be one the viewer sent.
    """
    viewer = viewer_address(viewer_header)
    hops = [hop.strip() for hop in (forwarded_for or "").split(",") if hop.strip()]
    if viewer is None or len(hops) < 2 or _canonical_ip(hops[-2]) != viewer:
        return None
    return viewer


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def came_through_cloudfront(presented: str | None, secrets: Iterable[SecretStr]) -> bool:
    """
    Phase 6.3 — whether a request carries the distribution's secret origin header.

    Compared as SHA-256 digests with `hmac.compare_digest`, so the time taken says
    nothing about a secret, its length included; every value is compared, whichever
    matches.
    """
    if not presented:
        return False
    digest = _digest(presented)
    matched = False
    for secret in secrets:
        matched |= hmac.compare_digest(digest, _digest(secret.get_secret_value()))
    return matched


def client_ip(request: Request) -> str:
    """Phase 6.3 — the client's IP: what the rate limits count, and what a visit is stored
    with (`visit_ip`). How it's decided: `client_ip_and_source`."""
    return client_ip_and_source(request)[0]


def client_ip_and_source(request: Request) -> tuple[str, str]:
    """
    Phase 6.3 — the client's IP, and how it was found: "cloudfront", "xff" or "socket".
    The one place that decides it. Each request's log line says the source, never the IP,
    so CloudWatch can show that shurly.griddo.io's requests are read through CloudFront.

    Behind CloudFront (shurly.griddo.io, 4.10) the ALB's peer is a CloudFront edge, and
    X-Forwarded-For's rightmost untrusted address is the edge's. CloudFront sends the
    viewer's own address in `CloudFront-Viewer-Address`, believed only on a request that
    carries the distribution's secret origin header: the ALB is shared and reachable
    directly, and anyone can send the viewer header, but not the secret. And only when
    it's the address CloudFront appended to X-Forwarded-For (`cloudfront_viewer`).
    Otherwise, and when that header is missing or doesn't parse, `resolve_client_ip`.
    """
    headers = request.headers
    forwarded_for = headers.get("x-forwarded-for")
    if settings.cloudfront_origin_secrets and came_through_cloudfront(
        headers.get(settings.cloudfront_origin_header), settings.cloudfront_origin_secrets
    ):
        viewer = cloudfront_viewer(headers.get(VIEWER_ADDRESS_HEADER), forwarded_for)
        if viewer is not None:
            return viewer, CLOUDFRONT
    return _resolve(
        request.client.host if request.client else None,
        forwarded_for,
        settings.trusted_proxies,
    )


def request_host(request: Request) -> str:
    """The host a request named, as its log line shows it: lowercased, without the port, at
    most 255 characters. Read by hand: a malformed Host header must never fail the line."""
    host = request.headers.get("host", "").strip().lower()
    if host.startswith("["):  # an IPv6 literal, "[2001:db8::1]:8000"
        end = host.find("]")
        host = host[: end + 1] if end != -1 else host
    else:
        host = host.split(":", 1)[0]
    return host[:255]


def forwarded_proto(scope) -> str | None:
    """
    Phase 6.3 — the scheme a trusted proxy says the client used: X-Forwarded-Proto, but only
    from a peer in TRUSTED_PROXIES, and its rightmost value, the one the nearest proxy wrote.
    None otherwise, or for anything but http and https.
    """
    client = scope.get("client")
    peer = client[0] if client else None
    if not peer or not settings.trusted_proxies:
        return None
    if not _addr_in_any_cidr(peer, settings.trusted_proxies):
        return None
    values = [
        value.decode("latin-1") for name, value in scope["headers"] if name == b"x-forwarded-proto"
    ]
    if not values:
        return None
    proto = ",".join(values).rsplit(",", 1)[-1].strip().lower()
    return proto if proto in ("http", "https") else None


class ForwardedProtoMiddleware:
    """
    Phase 6.3 — the request's scheme behind the ALB, which ends TLS (`forwarded_proto`), so what
    Starlette builds from it, like the trailing-slash redirect's absolute URL, stays https.

    What uvicorn's --proxy-headers did for the scheme, without its also replacing the client's
    address before the app runs: the image runs uvicorn with --no-proxy-headers, and `client_ip`
    alone decides the address.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            proto = forwarded_proto(scope)
            if proto is not None:
                if scope["type"] == "websocket":
                    proto = proto.replace("http", "ws")
                scope = {**scope, "scheme": proto}
        await self.app(scope, receive, send)


def visit_ip(request: Request) -> str:
    """
    The address a visit, or an orphan visit, is stored with: `client_ip`, then
    anonymized (Phase 3.9.5) unless ANONYMIZE_REMOTE_ADDR is off. Resolved first:
    truncating a proxy's address would store the wrong network.
    """
    ip = client_ip(request)
    return anonymize_ip(ip) if settings.anonymize_remote_addr else ip
