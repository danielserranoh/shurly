"""Tests for IP anonymization and trusted-proxy resolution (Phase 3.9.5 / 3.9.6)."""

from server.utils.network import anonymize_ip, resolve_client_ip


class TestAnonymizeIP:
    def test_ipv4_truncates_to_24(self):
        assert anonymize_ip("203.0.113.45") == "203.0.113.0"

    def test_ipv4_already_at_boundary(self):
        assert anonymize_ip("10.0.0.0") == "10.0.0.0"

    def test_ipv6_truncates_to_64(self):
        assert anonymize_ip("2001:db8:abcd:0012:0000:0000:0000:0001") == "2001:db8:abcd:12::"

    def test_invalid_input_passes_through(self):
        assert anonymize_ip("unknown") == "unknown"

    def test_none_passes_through(self):
        assert anonymize_ip(None) is None

    def test_no_full_ip_persisted(self):
        # Sanity: no original octet leaks
        out = anonymize_ip("198.51.100.77")
        assert "77" not in out
        assert out == "198.51.100.0"


class TestResolveClientIP:
    def test_no_xff_returns_socket(self):
        assert resolve_client_ip("203.0.113.10", None, []) == "203.0.113.10"

    def test_xff_ignored_without_trusted_proxies(self):
        # Even with an X-F-F header, untrusted source = use socket.
        assert (
            resolve_client_ip("203.0.113.10", "10.0.0.5", [])
            == "203.0.113.10"
        )

    def test_xff_honored_for_trusted_proxy(self):
        assert (
            resolve_client_ip("10.0.0.5", "203.0.113.99", ["10.0.0.0/8"])
            == "203.0.113.99"
        )

    def test_xff_ignored_for_untrusted_source(self):
        # Source not in CIDR allowlist → don't trust the header.
        assert (
            resolve_client_ip("198.51.100.7", "203.0.113.99", ["10.0.0.0/8"])
            == "198.51.100.7"
        )

    def test_xff_uses_leftmost_entry(self):
        assert (
            resolve_client_ip(
                "10.0.0.5",
                "203.0.113.42, 10.0.0.99, 192.168.1.1",
                ["10.0.0.0/8"],
            )
            == "203.0.113.42"
        )

    def test_unknown_socket_handled(self):
        assert resolve_client_ip(None, None, []) == "unknown"
