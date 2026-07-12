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
