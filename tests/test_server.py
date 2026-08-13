from __future__ import annotations

import http.client
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from headful_auth_tunnel.server import (
    BrowserSession,
    SessionStore,
    TunnelHTTPServer,
    make_handler,
)


class FakeController:
    def call(self, method, timeout=65, **kwargs):
        if method == "health":
            return {"status": "ok", "browser": True, "tabs": 1}
        if method == "meta":
            return {
                "url": "https://example.com",
                "viewport": {"width": 1440, "height": 1100},
            }
        if method == "tabs":
            return {"tabs": []}
        if method == "page_snapshot":
            return {"title": "Example", "elements": []}
        if method == "screenshot":
            return b"png"
        return {"ok": True, "method": method, **kwargs}


def start_server(config):
    server = TunnelHTTPServer(
        ("127.0.0.1", 0),
        make_handler(config, FakeController(), SessionStore()),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    connection.request(method, path, body=body, headers=headers or {})
    response = connection.getresponse()
    payload = response.read()
    result_headers = dict(response.getheaders())
    connection.close()
    return response.status, result_headers, payload


def test_login_uses_http_only_cookie_and_no_query_token(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        status, headers, body = request(server, "GET", f"/?token={config.auth_token}")
        assert status == 200
        assert b"Access token" in body
        assert "Set-Cookie" not in headers

        encoded = urlencode({"token": config.auth_token})
        status, headers, _ = request(
            server,
            "POST",
            "/session",
            encoded,
            {"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert status == 303
        cookie = headers["Set-Cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        assert config.auth_token not in cookie

        cookie_pair = cookie.split(";", 1)[0]
        status, _, payload = request(server, "GET", "/meta", headers={"Cookie": cookie_pair})
        assert status == 200
        assert json.loads(payload)["viewport"] == {
            "width": 1440,
            "height": 1100,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_forwarded_https_marks_session_cookie_secure(make_config):
    config = make_config(trust_forwarded_proto=True)
    server, thread = start_server(config)
    try:
        encoded = urlencode({"token": config.auth_token})
        status, headers, _ = request(
            server,
            "POST",
            "/session",
            encoded,
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Forwarded-Proto": "https",
            },
        )
        assert status == 303
        assert "Secure" in headers["Set-Cookie"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_bearer_auth_and_security_headers(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        status, headers, payload = request(
            server,
            "GET",
            "/meta",
            headers={"Authorization": f"Bearer {config.auth_token}"},
        )
        assert status == 200
        assert json.loads(payload)["url"] == "https://example.com"
        assert headers["Cache-Control"].startswith("no-store")
        assert headers["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_body_limit_returns_413(make_config):
    config = make_config(max_request_bytes=16)
    server, thread = start_server(config)
    try:
        status, _, payload = request(
            server,
            "POST",
            "/navigate",
            body=b"x" * 32,
            headers={
                "Authorization": f"Bearer {config.auth_token}",
                "Content-Type": "application/json",
            },
        )
        assert status == 413
        assert json.loads(payload)["error"] == "Request body is too large"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_session_store_expiry():
    store = SessionStore(ttl_seconds=1)
    token = store.create()
    assert store.valid(token)
    store._sessions[token] = time.time() - 1
    assert not store.valid(token)


def test_viewport_bounds_follow_runtime_resolution(make_config):
    session = BrowserSession(make_config(screen_width=3840, screen_height=2160))
    assert session._point(3839, 2159) == (3839, 2159)


class SnapshotPage:
    def __init__(self):
        self.closed = False
        self.arguments = None

    def is_closed(self):
        return self.closed

    def evaluate(self, script, arguments):
        self.arguments = arguments
        return {"arguments": arguments}


class SnapshotContext:
    def __init__(self, page):
        self.pages = [page]


def test_snapshot_can_explicitly_include_sensitive_values(make_config):
    session = BrowserSession(make_config())
    page = SnapshotPage()
    session.context = SnapshotContext(page)
    session.page = page

    result = session.page_snapshot(
        include_values=True,
        include_sensitive_values=True,
    )

    assert result["arguments"]["includeValues"] is True
    assert result["arguments"]["includeSensitiveValues"] is True


def test_browser_metadata_declares_headful_persistent_single_instance(make_config):
    session = BrowserSession(make_config())
    page = SnapshotPage()
    page.url = "https://example.com"
    page.title = lambda: "Example"
    session.context = SnapshotContext(page)
    session.page = page

    first = session.meta()
    second = session.meta()

    assert first["browser_mode"] == "headful"
    assert first["persistent_profile"] is True
    assert first["browser_instance_id"] == second["browser_instance_id"]


def _session_cookie(server, config):
    encoded = urlencode({"token": config.auth_token})
    status, headers, _ = request(
        server,
        "POST",
        "/session",
        encoded,
        {"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert status == 303
    return headers["Set-Cookie"].split(";", 1)[0]


def test_options_get_resource_has_security_headers_and_allow(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        cookie_pair = _session_cookie(server, config)
        status, headers, _ = request(
            server,
            "OPTIONS",
            "/meta",
            headers={"Cookie": cookie_pair},
        )
        assert status == 204
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in headers
        assert headers["Cache-Control"].startswith("no-store")
        assert headers["Allow"] == "GET, HEAD"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_options_post_resource_allow(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        status, headers, _ = request(server, "OPTIONS", "/session")
        assert status == 204
        assert headers["Allow"] == "POST"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_options_unknown_path_is_404(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        status, _, payload = request(server, "OPTIONS", "/no-such-route")
        assert status == 404
        assert json.loads(payload)["error"] == "Not found"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_trace_get_resource_is_405_with_security_headers(make_config):
    config = make_config()
    server, thread = start_server(config)
    try:
        cookie_pair = _session_cookie(server, config)
        status, headers, _ = request(
            server,
            "TRACE",
            "/meta",
            headers={"Cookie": cookie_pair},
        )
        assert status == 405
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert "Content-Security-Policy" in headers
        assert headers["Cache-Control"].startswith("no-store")
        assert headers["Allow"] == "GET, HEAD"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_options_includes_hsts_when_tls_configured(make_config):
    # tls_enabled is a Path-presence check; dummy paths flip HSTS without
    # wrapping the test server in TLS or adding cert-file fixtures.
    config = make_config(tls_cert=Path("dummy.crt"), tls_key=Path("dummy.key"))
    server, thread = start_server(config)
    try:
        status, headers, _ = request(server, "OPTIONS", "/health")
        assert status == 204
        assert headers["Strict-Transport-Security"] == "max-age=31536000"
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Allow"] == "GET, HEAD"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
