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
        self.frames = []

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
    # _check_final_url re-validates the landed URL; allow example.com
    # explicitly so the guard short-circuits without DNS (netless sandboxes).
    session = BrowserSession(make_config(allowed_hosts=("example.com",)))
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


class LifecyclePage:
    def __init__(self, *, closed=False, url="about:blank"):
        self.closed = closed
        self.url = url
        self.viewport = None
        self.goto_calls = []
        self.frames = []

    def is_closed(self):
        return self.closed

    def set_viewport_size(self, viewport):
        if self.closed:
            raise RuntimeError("Page is closed")
        self.viewport = viewport

    def goto(self, url, wait_until=None, timeout=None):
        if self.closed:
            raise RuntimeError("Page is closed")
        self.goto_calls.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        self.url = url

    def title(self):
        return ""


class LifecycleContext:
    def __init__(self, pages=None):
        self.pages = list(pages or [])

    def new_page(self):
        page = LifecyclePage()
        self.pages.append(page)
        return page


def _allow_base(url, refresh=False, **_kwargs):
    return NavigationDecision(True, "allowed", url)


def test_on_page_rejects_closed_incoming_page(make_config):
    session = BrowserSession(make_config())
    live = LifecyclePage(url="https://example.com/app")
    closed_popup = LifecyclePage(closed=True, url="about:blank")
    session.context = LifecycleContext([live, closed_popup])
    session.page = None

    session._on_page(closed_popup)

    assert session.page is None
    assert closed_popup.viewport is None


def test_on_page_does_not_install_delayed_closed_popup_over_invalid_current(make_config):
    session = BrowserSession(make_config())
    dead_current = LifecyclePage(closed=True, url="https://example.com/old")
    live = LifecyclePage(url="https://example.com/keep")
    closed_popup = LifecyclePage(closed=True, url="about:blank")
    session.context = LifecycleContext([dead_current, live, closed_popup])
    session.page = dead_current

    session._on_page(closed_popup)

    assert session.page is dead_current
    assert session._current_page() is live


def test_on_page_does_not_retarget_live_current_tab(make_config):
    session = BrowserSession(make_config())
    current = LifecyclePage(url="https://example.com/app")
    popup = LifecyclePage(url="https://example.com/popup")
    session.context = LifecycleContext([current, popup])
    session.page = current

    session._on_page(popup)

    assert session.page is current
    assert popup.viewport == session.viewport


def test_on_page_adopts_live_page_when_current_is_gone(make_config):
    session = BrowserSession(make_config())
    incoming = LifecyclePage(url="https://example.com/fresh")
    session.context = LifecycleContext([incoming])
    session.page = LifecyclePage(closed=True)

    session._on_page(incoming)

    assert session.page is incoming
    assert incoming.viewport == session.viewport


def test_current_page_recovers_zero_tabs_at_configured_base_url(make_config):
    session = BrowserSession(make_config(base_url="https://example.com/login"))
    session.policy.validate = _allow_base
    closed = LifecyclePage(closed=True)
    session.context = LifecycleContext([closed])
    session.page = closed

    recovered = session._current_page()

    assert recovered is not closed
    assert recovered.closed is False
    assert session.page is recovered
    assert recovered.goto_calls == [
        {
            "url": "https://example.com/login",
            "wait_until": "domcontentloaded",
            "timeout": session.config.navigation_timeout_ms,
        }
    ]
    assert recovered.url == "https://example.com/login"
    assert recovered.viewport == session.viewport


def test_current_page_uses_normalized_recovery_url(make_config):
    session = BrowserSession(make_config(base_url="https://example.com"))
    session.policy.validate = lambda url, refresh=False, **_kwargs: NavigationDecision(
        True, "allowed", "https://example.com/"
    )
    session.context = LifecycleContext([])
    session.page = None

    recovered = session._current_page()

    assert recovered.goto_calls[0]["url"] == "https://example.com/"


class FakePage:
    def __init__(self, url="", *, navigate_on_click=None):
        self.url = url
        self.goto_calls = []
        self.frames = []
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
    fake_page = types.SimpleNamespace(url="https://ok.test/", frames=[])

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


class FramePage(FakePage):
    def __init__(self, url="https://ok.test/"):
        super().__init__(url=url)
        self.screenshot_calls = 0
        self.main_frame = FakeFrame(url, page=self, parent=None)
        self.frames = [self.main_frame]

    def screenshot(self, **_kwargs):
        self.screenshot_calls += 1
        return b"png"


class FakeFrame:
    def __init__(self, url, *, page, parent, unreadable=False):
        self._url = url
        self.page = page
        self.parent_frame = parent
        self.unreadable = unreadable
        self.goto_calls = []

    @property
    def url(self):
        if self.unreadable:
            raise RuntimeError("frame URL unavailable")
        return self._url

    def goto(self, url, **_kwargs):
        self.goto_calls.append(url)
        self._url = url
        self.unreadable = False


def test_frame_navigation_revalidates_same_host_with_fresh_dns_every_time(make_config):
    session = BrowserSession(make_config())
    recorded = []

    class RecordingPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            recorded.append((url, allow_non_network, refresh))
            return NavigationDecision(True, "ok", url)

    session.policy = RecordingPolicy()
    page = FramePage("https://same.test/")
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page

    session._on_frame_navigated(page.main_frame)
    session._on_frame_navigated(page.main_frame)

    assert recorded == [
        ("https://same.test/", True, True),
        ("https://same.test/", True, True),
    ]


def test_blocked_subframe_is_quarantined_and_latched(make_config):
    session = BrowserSession(make_config(denied_hosts=("blocked.test",)))
    page = FramePage("https://ok.test/")
    subframe = FakeFrame(
        "https://blocked.test/secret",
        page=page,
        parent=page.main_frame,
    )
    page.frames.append(subframe)
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page

    session._on_frame_navigated(subframe)

    assert subframe.goto_calls == ["about:blank"]
    assert page.goto_calls == []
    with pytest.raises(RequestError) as exc:
        session.screenshot()
    assert exc.value.status == 403
    assert page.screenshot_calls == 0


def test_unreadable_subframe_fails_closed(make_config):
    session = BrowserSession(make_config(allowed_hosts=("ok.test",)))
    page = FramePage("https://ok.test/")
    subframe = FakeFrame("", page=page, parent=page.main_frame, unreadable=True)
    page.frames.append(subframe)
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page

    session._on_frame_navigated(subframe)

    assert subframe.goto_calls == ["about:blank"]
    with pytest.raises(RequestError) as exc:
        session.page_snapshot()
    assert exc.value.status == 403


def test_screenshot_revalidates_subframes_if_event_hook_was_missed(make_config):
    session = BrowserSession(make_config())

    class DeterministicPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            if "blocked.test" in url:
                return NavigationDecision(False, "blocked by test policy", None)
            return NavigationDecision(True, "ok", url)

    session.policy = DeterministicPolicy()
    page = FramePage("https://ok.test/")
    subframe = FakeFrame(
        "https://blocked.test/secret",
        page=page,
        parent=page.main_frame,
    )
    page.frames.append(subframe)
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page

    with pytest.raises(RequestError) as exc:
        session.screenshot()

    assert exc.value.status == 403
    assert subframe.goto_calls == ["about:blank"]
    assert page.screenshot_calls == 0


def test_unreadable_page_url_fails_closed(make_config):
    session = BrowserSession(make_config())

    class UnreadablePage(FakePage):
        @property
        def url(self):
            raise RuntimeError("URL unavailable")

        @url.setter
        def url(self, value):
            self._stored_url = value

    page = UnreadablePage("https://ok.test/")

    with pytest.raises(RequestError) as exc:
        session._check_final_url(page)

    assert exc.value.status == 403
    assert page.goto_calls == ["about:blank"]


def test_browser_action_refuses_already_blocked_page_before_click(make_config):
    session = BrowserSession(make_config(denied_hosts=("blocked.test",)))
    fake_page = FakePage(url="https://blocked.test/already-there")
    clicks = []
    fake_page.mouse = types.SimpleNamespace(click=lambda x, y: clicks.append((x, y)))
    session.context = types.SimpleNamespace(pages=[fake_page])
    session.page = fake_page

    with pytest.raises(RequestError) as exc:
        session.click(100, 100)

    assert exc.value.status == 403
    assert clicks == []
    assert fake_page.goto_calls == ["about:blank"]


def test_blocked_latch_uses_monotonic_page_id(make_config):
    session = BrowserSession(make_config())
    page = FramePage("https://ok.test/")
    page_id = session._page_id(page)

    session._latch_blocked_page(page, "blocked for test")

    assert session._blocked_page_reasons == {page_id: "blocked for test"}
    with pytest.raises(RequestError) as exc:
        session._check_final_url(page)
    assert exc.value.status == 403
    assert session._blocked_page_reasons == {}


def test_frame_dns_churn_is_bounded_and_fails_closed(make_config, monkeypatch):
    session = BrowserSession(make_config())
    recorded = []

    class RecordingPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            recorded.append((url, refresh))
            return NavigationDecision(True, "ok", url)

    session.policy = RecordingPolicy()
    page = FramePage("https://burst.test/")
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page
    monkeypatch.setattr(time, "monotonic", lambda: 100.0)

    for _ in range(session._frame_dns_max_per_window):
        session._on_frame_navigated(page.main_frame)
    session._on_frame_navigated(page.main_frame)

    assert len(recorded) == session._frame_dns_max_per_window
    assert page.goto_calls == ["about:blank"]
    with pytest.raises(RequestError) as exc:
        session._check_final_url(page)
    assert exc.value.status == 403
    assert "DNS churn" in exc.value.message


def test_frame_enumeration_failure_fails_closed(make_config):
    session = BrowserSession(make_config())

    class BrokenFramesPage(FakePage):
        @property
        def frames(self):
            raise RuntimeError("frame inventory unavailable")

        @frames.setter
        def frames(self, _value):
            pass

    page = BrokenFramesPage("https://ok.test/")

    with pytest.raises(RequestError) as exc:
        session._check_final_url(page)

    assert exc.value.status == 403
    assert "enumerate page frames" in exc.value.message
    assert page.goto_calls == ["about:blank"]


def test_defensive_frame_sweep_uses_same_dns_budget(make_config, monkeypatch):
    session = BrowserSession(make_config())
    recorded = []

    class RecordingPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            recorded.append((url, refresh))
            return NavigationDecision(True, "ok", url)

    session.policy = RecordingPolicy()
    page = FramePage("https://same.test/")
    for i in range(session._frame_dns_max_per_window):
        page.frames.append(
            FakeFrame(f"https://same.test/frame-{i}", page=page, parent=page.main_frame)
        )
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page
    monkeypatch.setattr(time, "monotonic", lambda: 200.0)

    with pytest.raises(RequestError) as exc:
        session.screenshot()

    assert exc.value.status == 403
    assert "DNS churn" in exc.value.message
    assert len(recorded) == session._frame_dns_max_per_window
    assert page.screenshot_calls == 0


def test_global_frame_dns_budget_bounds_unique_hosts_and_prunes(make_config, monkeypatch):
    session = BrowserSession(make_config())
    recorded = []
    clock = {"now": 300.0}

    class RecordingPolicy:
        def validate(self, url, *, allow_non_network=False, refresh=False):
            recorded.append((url, refresh))
            return NavigationDecision(True, "ok", url)

    session.policy = RecordingPolicy()
    page = FramePage("https://root.test/")
    session.context = types.SimpleNamespace(pages=[page])
    session.page = page
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    for i in range(session._frame_dns_global_max_per_window):
        frame = FakeFrame(
            f"https://host-{i}.test/",
            page=page,
            parent=page.main_frame,
        )
        session._on_frame_navigated(frame)

    overflow = FakeFrame(
        "https://overflow.test/",
        page=page,
        parent=page.main_frame,
    )
    session._on_frame_navigated(overflow)

    assert len(recorded) == session._frame_dns_global_max_per_window
    assert overflow.goto_calls == ["about:blank"]
    assert len(session._frame_dns_events) <= session._frame_dns_global_max_per_window

    clock["now"] += session._frame_dns_window_seconds + 0.1
    fresh = FakeFrame("https://fresh.test/", page=page, parent=page.main_frame)
    session._on_frame_navigated(fresh)

    assert list(session._frame_dns_events) == ["fresh.test"]
    assert len(session._frame_dns_global_events) == 1
