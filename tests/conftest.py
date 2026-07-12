from __future__ import annotations

from pathlib import Path

import pytest

from headful_auth_tunnel.config import Config


@pytest.fixture
def make_config(tmp_path: Path):
    def factory(**overrides):
        values = {
            "bind_host": "127.0.0.1",
            "port": 6080,
            "base_url": "https://example.com",
            "profile_dir": tmp_path / "profile",
            "screen_width": 1440,
            "screen_height": 1100,
            "locale": "pt-PT",
            "timezone_id": "Europe/Lisbon",
            "screenshot_interval_ms": 2000,
            "max_request_bytes": 1024,
            "socket_timeout_seconds": 5,
            "navigation_timeout_ms": 30000,
            "auth_token": "a" * 32,
            "token_file": tmp_path / "token",
            "session_cookie_name": "headful_auth_session",
            "allow_query_token": False,
            "allow_private_network_navigation": False,
            "allowed_hosts": (),
            "denied_hosts": (),
            "expose_health_details": False,
            "tls_cert": None,
            "tls_key": None,
            "max_dom_text_chars": 20000,
            "max_dom_elements": 250,
        }
        values.update(overrides)
        values["profile_dir"].mkdir(parents=True, exist_ok=True)
        return Config(**values)

    return factory
