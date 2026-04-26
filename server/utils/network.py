"""Network address helpers — IP anonymization and proxy trust resolution."""

import ipaddress
from collections.abc import Iterable


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

    If the request's source IP is in `trusted_proxies`, honor the leftmost
    `X-Forwarded-For` entry. Otherwise return the socket address (never trust
    `X-Forwarded-For` from arbitrary clients — they can spoof it).
    """
    socket_addr = socket_addr or "unknown"
    if not forwarded_for or not list(trusted_proxies):
        return socket_addr
    if not _addr_in_any_cidr(socket_addr, trusted_proxies):
        return socket_addr
    first = forwarded_for.split(",")[0].strip()
    return first or socket_addr
