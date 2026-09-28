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
