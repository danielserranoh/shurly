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
    socket_addr = socket_addr or "unknown"
    trusted = list(trusted_proxies)
    if not forwarded_for or not trusted or not _addr_in_any_cidr(socket_addr, trusted):
        return socket_addr
    hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _addr_in_any_cidr(hop, trusted):
            return hop
    return hops[0] if hops else socket_addr


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
    """
    Phase 6.3 — the client's IP: what the rate limits count, and what a visit is stored
    with (`visit_ip`). The one place that decides it.

    Behind CloudFront (shurly.griddo.io, 4.10) the ALB's peer is a CloudFront edge, and
    X-Forwarded-For's rightmost untrusted address is the edge's. CloudFront sends the
    viewer's own address in `CloudFront-Viewer-Address`, believed only on a request that
    carries the distribution's secret origin header: the ALB is shared and reachable
    directly, and anyone can send the viewer header, but not the secret. Otherwise, and
    when that header is missing or doesn't parse, `resolve_client_ip`.
    """
    headers = request.headers
    if settings.cloudfront_origin_secrets and came_through_cloudfront(
        headers.get(settings.cloudfront_origin_header), settings.cloudfront_origin_secrets
    ):
        viewer = viewer_address(headers.get(VIEWER_ADDRESS_HEADER))
        if viewer is not None:
            return viewer
    return resolve_client_ip(
        request.client.host if request.client else None,
        headers.get("x-forwarded-for"),
        settings.trusted_proxies,
    )


def visit_ip(request: Request) -> str:
    """
    The address a visit, or an orphan visit, is stored with: `client_ip`, then
    anonymized (Phase 3.9.5) unless ANONYMIZE_REMOTE_ADDR is off. Resolved first:
    truncating a proxy's address would store the wrong network.
    """
    ip = client_ip(request)
    return anonymize_ip(ip) if settings.anonymize_remote_addr else ip
