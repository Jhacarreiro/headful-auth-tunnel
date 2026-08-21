from __future__ import annotations

import http.client
import json
import threading
import time
import types
from urllib.parse import urlencode

import pytest

from headful_auth_tunnel.security import NavigationDecision
from headful_auth_tunnel.server import (
    BrowserSession,
    RequestError,
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
        self.url = "https://example.com"
        self.goto_calls = []

    def is_closed(self):
        return self.closed

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        self.url = url

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


class FakePage:
    def __init__(self, url="", *, navigate_on_click=None):
        self.url = url
        self.goto_calls = []
        self.navigate_on_click = navigate_on_click
        self.mouse = types.SimpleNamespace(click=self._click)
        self.closed = False

    def is_closed(self):
        return self.closed

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        self.url = url

    def _click(self, x, y):
        if self.navigate_on_click is not None:
            self.url = self.navigate_on_click


def test_final_url_check_refreshes_policy_every_landing(make_config):
    session = BrowserSession(make_config())
    recorded = []

    class RecordingPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            recorded.append(
                {
                    "url": url,
                    "allow_non_network": allow_non_network,
                    "refresh": refresh,
                }
            )
            return NavigationDecision(True, "ok", url)

    session.policy = RecordingPolicy()
    fake_page = types.SimpleNamespace(url="https://ok.test/")

    result = session._check_final_url(fake_page)

    assert recorded[0]["refresh"] is True
    assert result == "https://ok.test/"


def test_final_url_check_quarantines_blocked_page(make_config):
    session = BrowserSession(make_config(denied_hosts=("blocked.test",)))
    fake_page = FakePage(url="https://blocked.test/x")

    with pytest.raises(RequestError) as exc:
        session._check_final_url(fake_page)

    assert exc.value.status == 403
    assert fake_page.goto_calls == ["about:blank"]


def test_browser_action_click_revalidates_final_url(make_config):
    session = BrowserSession(make_config(denied_hosts=("blocked.test",)))
    fake_page = FakePage(
        url="https://ok.test/",
        navigate_on_click="https://blocked.test/landed",
    )
    session.context = types.SimpleNamespace(pages=[fake_page])
    session.page = fake_page

    with pytest.raises(RequestError) as exc:
        session.click(100, 100)

    assert exc.value.status == 403
    assert fake_page.goto_calls == ["about:blank"]
