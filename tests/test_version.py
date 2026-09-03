from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import tomllib

from headful_auth_tunnel import __version__
from headful_auth_tunnel.server import make_handler


def test_package_and_server_versions_match_pyproject():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    expected = project["project"]["version"]
    handler = make_handler(SimpleNamespace(), None, None)

    assert __version__ == expected
    assert handler.server_version == f"HeadfulAuthTunnel/{expected}"
