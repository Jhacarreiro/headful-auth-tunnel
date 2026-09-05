from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from headful_auth_tunnel.browser import CDPBrowserBackend

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

DRIVER = r"""
import os
import sys
import time
import types
from pathlib import Path

class FakePage:
    def __init__(self):
        self.url = "https://93.184.216.34/"
    def set_viewport_size(self, viewport): pass
    def goto(self, url, wait_until=None, timeout=None): self.url = url
    def is_closed(self): return False
    def title(self): return "Fake"

class FakeContext:
    def __init__(self): self.pages = []
    def route(self, *args): pass
    def route_web_socket(self, *args): pass
    def on(self, *args): pass
    def new_page(self): return FakePage()

class FakeStealthySession:
    def __init__(self, **kwargs): self.context = FakeContext()
    def start(self):
        marker = os.environ.get("HAT_START_MARKER")
        if marker: Path(marker).write_text("starting")
        time.sleep(float(os.environ.get("HAT_HOLD_START", "0")))
    def close(self):
        marker = os.environ.get("HAT_CLOSE_MARKER")
        if marker: Path(marker).write_text("closed")

scrapling = types.ModuleType("scrapling")
fetchers = types.ModuleType("scrapling.fetchers")
fetchers.StealthySession = FakeStealthySession
sys.modules["scrapling"] = scrapling
sys.modules["scrapling.fetchers"] = fetchers

from headful_auth_tunnel.server import main
main()
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _spawn_server(tmp_path: Path, *, hold_start: float = 0.0):
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "AUTH_TOKEN": "x" * 32,
            "BASE_URL": "https://93.184.216.34/",
            "BIND_HOST": "127.0.0.1",
            "PORT": str(port),
            "PROFILE_DIR": str(tmp_path / "profile"),
            "PYTHONPATH": str(REPO_ROOT),
            "HAT_HOLD_START": str(hold_start),
            "HAT_START_MARKER": str(tmp_path / "start.marker"),
            "HAT_CLOSE_MARKER": str(tmp_path / "close.marker"),
        }
    )
    (tmp_path / "profile").mkdir()
    proc = subprocess.Popen(
        [PYTHON, "-c", DRIVER],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc, port


def _terminate_and_collect(proc: subprocess.Popen, signum: int) -> str:
    os.kill(proc.pid, signum)
    try:
        output, _ = proc.communicate(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        output, _ = proc.communicate(timeout=3)
        pytest.fail(f"server did not exit after signal {signum}:\n{output[-2000:]}")
    assert proc.returncode == 0, output[-2000:]
    return output


def test_sigterm_during_browser_startup_closes_managed_session(tmp_path):
    proc, _ = _spawn_server(tmp_path, hold_start=0.8)
    assert _wait_for((tmp_path / "start.marker").exists)

    output = _terminate_and_collect(proc, signal.SIGTERM)

    assert "initiating graceful shutdown" in output
    assert "Shutdown requested during browser startup" in output
    assert (tmp_path / "close.marker").read_text() == "closed"


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_signals_while_serving_exit_cleanly(tmp_path, signum):
    proc, port = _spawn_server(tmp_path)

    def healthy() -> bool:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.3)
            conn.request("GET", "/health")
            response = conn.getresponse()
            response.read()
            conn.close()
            return response.status == 200
        except OSError:
            return False

    assert _wait_for(healthy)
    output = _terminate_and_collect(proc, signum)

    assert "initiating graceful shutdown" in output
    assert (tmp_path / "close.marker").read_text() == "closed"


def test_cdp_close_detaches_without_closing_external_browser(make_config):
    events = []

    class FakePlaywright:
        def stop(self):
            events.append("playwright.stop")

    class FakeBrowser:
        def close(self):
            events.append("browser.close")

    backend = CDPBrowserBackend(
        make_config(
            browser_mode="cdp",
            cdp_endpoint="http://127.0.0.1:9223",
            cdp_target="example",
            profile_dir=None,
        ),
        lambda *_: None,
        lambda *_: None,
        lambda *_: None,
    )
    backend._playwright = FakePlaywright()
    backend._browser = FakeBrowser()
    backend.context = object()
    backend._attached_pages = [object()]

    backend.close()

    assert events == ["playwright.stop"]
    assert backend._browser is None
    assert backend.context is None
    assert backend._attached_pages == []


def _write_executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\nset -eu\n" + textwrap.dedent(body))
    path.chmod(0o755)


def test_run_foreground_records_and_cleans_child_pids(tmp_path):
    fake_bin = tmp_path / "bin"
    runtime = tmp_path / "runtime"
    fake_bin.mkdir()
    runtime.mkdir()
    xvfb = fake_bin / "Xvfb"
    app = fake_bin / "headful-auth-tunnel"
    _write_executable(
        xvfb,
        """
        trap 'exit 0' TERM INT
        while :; do sleep 1; done
        """,
    )
    _write_executable(
        app,
        """
        trap 'exit 0' TERM INT
        while :; do sleep 1; done
        """,
    )
    env = os.environ.copy()
    env.update({"PATH": f"{fake_bin}:{env['PATH']}", "RUNTIME_DIR": str(runtime)})
    proc = subprocess.Popen(
        [str(REPO_ROOT / "scripts/run-foreground.sh"), str(app)],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert _wait_for(lambda: (runtime / "xvfb.pid").exists(), timeout=3)
        assert _wait_for(lambda: (runtime / "tunnel.pid").exists(), timeout=3)
        xvfb_pid = int((runtime / "xvfb.pid").read_text().strip())
        app_pid = int((runtime / "tunnel.pid").read_text().strip())
        assert Path(f"/proc/{xvfb_pid}").exists()
        assert Path(f"/proc/{app_pid}").exists()

        proc.send_signal(signal.SIGTERM)
        proc.communicate(timeout=6)

        assert not (runtime / "xvfb.pid").exists()
        assert not (runtime / "tunnel.pid").exists()
        assert not Path(f"/proc/{xvfb_pid}").exists()
        assert not Path(f"/proc/{app_pid}").exists()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)


def test_stop_script_continues_after_refusal_and_cleans_both_pid_files(tmp_path):
    runtime = tmp_path / "runtime"
    fake_bin = tmp_path / "bin"
    runtime.mkdir()
    fake_bin.mkdir()
    xvfb_exe = fake_bin / "Xvfb"
    xvfb_exe.symlink_to("/bin/sleep")

    unrelated = subprocess.Popen(["/bin/sleep", "30"])
    xvfb = subprocess.Popen([str(xvfb_exe), "30"])
    (runtime / "tunnel.pid").write_text(f"{unrelated.pid}\n")
    (runtime / "xvfb.pid").write_text(f"{xvfb.pid}\n")
    env = os.environ.copy()
    env["RUNTIME_DIR"] = str(runtime)
    try:
        result = subprocess.run(
            [str(REPO_ROOT / "scripts/stop.sh")],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 1
        assert "Refusing to stop" in result.stderr
        assert unrelated.poll() is None
        assert _wait_for(lambda: xvfb.poll() is not None, timeout=2)
        assert not (runtime / "tunnel.pid").exists()
        assert not (runtime / "xvfb.pid").exists()
    finally:
        for proc in (unrelated, xvfb):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2)


def test_systemd_unit_uses_ephemeral_runtime_directory():
    unit = (REPO_ROOT / "deploy/systemd/headful-auth-tunnel.service").read_text()
    assert "RuntimeDirectory=headful-auth-tunnel" in unit
    assert "RuntimeDirectoryMode=0750" in unit
    assert "Environment=RUNTIME_DIR=/run/headful-auth-tunnel" in unit
