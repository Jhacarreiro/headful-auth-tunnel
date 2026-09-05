from __future__ import annotations

import socket

import pytest

from headful_auth_tunnel.security import NavigationPolicy, validate_navigation_url


def public_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost",
        "http://127.0.0.1",
        "http://192.168.1.10",
        "http://169.254.169.254/latest/meta-data",
        "http://service.internal",
        "http://printer.local",
        "http://singlelabel",
        "file:///etc/passwd",
    ],
)
def test_internal_and_non_http_destinations_are_blocked(url, make_config):
    decision = validate_navigation_url(url, make_config())
    assert decision.allowed is False


def test_public_hostname_is_allowed(monkeypatch, make_config):
    monkeypatch.setattr(socket, "getaddrinfo", public_dns)
    decision = validate_navigation_url("https://example.com/login", make_config())
    assert decision.allowed is True


def test_public_name_resolving_private_is_blocked(monkeypatch, make_config):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 443))],
    )
    decision = validate_navigation_url("https://example.com", make_config())
    assert decision.allowed is False


def test_allowlist_can_override_internal_default(make_config):
    config = make_config(allowed_hosts=("auth.internal",))
    decision = validate_navigation_url("https://auth.internal/login", config)
    assert decision.allowed is True


def test_denylist_has_highest_precedence(make_config):
    config = make_config(allowed_hosts=("blocked.example",), denied_hosts=("blocked.example",))
    decision = validate_navigation_url("https://blocked.example", config)
    assert decision.allowed is False


def test_private_network_switch_allows_internal(make_config):
    config = make_config(allow_private_network_navigation=True)
    decision = validate_navigation_url("http://192.168.1.10", config)
    assert decision.allowed is True


def test_route_policy_only_allows_safe_non_network_schemes(make_config):
    policy = NavigationPolicy(make_config())
    assert policy.validate("blob:https://example.com/id", allow_non_network=True).allowed
    assert not policy.validate("file:///etc/passwd", allow_non_network=True).allowed
    assert not policy.validate("ws://127.0.0.1/socket", allow_non_network=True).allowed


def test_invalid_port_is_rejected(make_config):
    decision = validate_navigation_url("https://example.com:99999", make_config())
    assert decision.allowed is False


def test_overlong_url_is_rejected_before_resolution(monkeypatch, make_config):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("DNS should not run")
    )
    config = make_config(max_url_chars=64)
    decision = validate_navigation_url("https://example.com/" + "a" * 80, config)
    assert decision.allowed is False
    assert decision.reason == "URL is too long"


def test_uts46_nontransitional_hostname_is_used_for_dns(monkeypatch, make_config):
    seen = []

    def capture_dns(host, port, *args, **kwargs):
        seen.append((host, port))
        return public_dns()

    monkeypatch.setattr(socket, "getaddrinfo", capture_dns)
    decision = validate_navigation_url("https://faß.de:8443/login", make_config())

    assert decision.allowed is True
    assert seen == [("xn--fa-hia.de", 8443)]


def test_uts46_mapping_is_applied_before_denylist(monkeypatch, make_config):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *args, **kwargs: pytest.fail("DNS should not run")
    )
    config = make_config(denied_hosts=("exakple.com",))
    decision = validate_navigation_url("https://exaKple.com/login", config)

    assert decision.allowed is False
    assert decision.reason == "Hostname is denied by DENIED_HOSTS"


def test_navigation_policy_cache_uses_canonical_uts46_origin(monkeypatch, make_config):
    calls = []

    def capture_dns(host, port, *args, **kwargs):
        calls.append((host, port))
        return public_dns()

    monkeypatch.setattr(socket, "getaddrinfo", capture_dns)
    policy = NavigationPolicy(make_config())

    first = policy.validate("https://exaKple.com/one")
    second = policy.validate("https://exakple.com/two")

    assert first.allowed is True
    assert second.allowed is True
    assert calls == [("exakple.com", 443)]


def test_ipv6_literals_and_invalid_ports_are_handled_before_allow(make_config):
    public = validate_navigation_url("http://[2001:4860:4860::8888]:8443/login", make_config())
    assert public.allowed is True
    assert public.reason == "Public IP address"

    loopback = validate_navigation_url("http://[::1]:8080/", make_config())
    assert loopback.allowed is False
    assert loopback.reason == "Private or special-use IP addresses are blocked"

    invalid = validate_navigation_url(
        "https://93.184.216.34:99999/",
        make_config(allow_private_network_navigation=True),
    )
    assert invalid.allowed is False
    assert invalid.reason == "URL contains an invalid port"
