"""The engine host's move of the console listener and its certificate expiry warning."""

from __future__ import annotations

import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from ceres.__internal__.core import NativeServer
from ceres.__internal__.host import _expiry_warning, _move_console_listener
from ceres.config import Config, ConfigCheckType, ServerConfig, ServerHTTPConfig
from ceres.error import ConfigCombinedError, ConfigValidationError

if TYPE_CHECKING:
    from pathlib import Path


def _certificate(directory: Path) -> ServerConfig:
    subprocess.run(
        [
            *("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "90"),
            *("-subj", "/CN=localhost", "-keyout", "server.key", "-out", "server.crt"),
        ],
        cwd=directory,
        check=True,
        capture_output=True,
    )
    return ServerConfig(
        https={"cert": str(directory / "server.crt"), "key": str(directory / "server.key")}
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl for a certificate")
def test_certificates_near_expiry_draw_a_warning(tmp_path: Path) -> None:
    server = _certificate(tmp_path)
    expiry = NativeServer.certificate_expiry(server)
    assert expiry is not None
    expires = datetime.fromtimestamp(expiry, UTC)
    replace = "Run `ceres generate certificate --force` to replace it."

    assert _expiry_warning(server, expires - timedelta(days=30)) is None
    assert _expiry_warning(server, expires - timedelta(days=10)) == (
        f"The HTTPS certificate {tmp_path / 'server.crt'} expires on {expires:%Y-%m-%d}, "
        f"in 10 days. {replace}"
    )
    assert _expiry_warning(server, expires - timedelta(hours=3)) == (
        f"The HTTPS certificate {tmp_path / 'server.crt'} expires on {expires:%Y-%m-%d}, "
        f"in 1 day. {replace}"
    )
    assert _expiry_warning(server, expires + timedelta(seconds=1)) == (
        f"The HTTPS certificate {tmp_path / 'server.crt'} expired on {expires:%Y-%m-%d}. {replace}"
    )


def test_no_https_listener_draws_no_warning() -> None:
    assert _expiry_warning(ServerConfig(http={"port": 8080}), datetime.now(UTC)) is None


async def test_the_server_check_names_the_command_for_a_missing_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ConfigCombinedError) as raised:
        await Config.load({"server": {"https": {}}}, checks=(ConfigCheckType.SERVER,))

    [error] = raised.value.errors
    assert isinstance(error, ConfigValidationError)
    [problem] = error.problems
    assert problem.location == ["server", "https"]
    assert problem.message == (
        ".ceres/tls/server.crt does not exist. Run `ceres generate certificate` to create it."
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl for a certificate")
async def test_the_server_check_passes_a_loadable_certificate(tmp_path: Path) -> None:
    _certificate(tmp_path)
    https = {"cert": str(tmp_path / "server.crt"), "key": str(tmp_path / "server.key")}

    config = await Config.load({"server": {"https": https}}, checks=(ConfigCheckType.SERVER,))

    assert config.server.https is not None


def test_the_https_listener_moves_when_there_is_one() -> None:
    server = ServerConfig(https={"port": 8443}, http={"port": 8080, "redirect": True})

    moved = _move_console_listener(server, 9000)

    assert moved.https is not None
    assert moved.https.port == 9000
    assert moved.http == ServerHTTPConfig(port=8080, redirect=True)


def test_the_http_listener_moves_without_https() -> None:
    moved = _move_console_listener(ServerConfig(http={"port": 8080}), 9000)

    assert moved.https is None
    assert moved.http == ServerHTTPConfig(port=9000)


def test_a_section_without_listeners_gains_an_http_one() -> None:
    moved = _move_console_listener(ServerConfig(), 9000)

    assert moved.https is None
    assert moved.http == ServerHTTPConfig(port=9000)
