"""The engine host's dev listener and its certificate expiry warning."""

from __future__ import annotations

import subprocess
import sysconfig
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ceres.__internal__.core import NativeServer
from ceres.__internal__.host import _dev_listener, _expiry_warning
from ceres.config import Config, ConfigCheckType, ServerConfig, ServerHTTPConfig
from ceres.error import ConfigCombinedError, ConfigValidationError

CERES = Path(sysconfig.get_path("scripts")) / "ceres"
"""The CLI binary installed beside the package, which writes the certificates under test."""


def _generate_certificate(project: Path) -> None:
    (project / "ceres.yaml").touch()
    subprocess.run([CERES, "generate", "certificate"], cwd=project, check=True, capture_output=True)


def test_certificates_near_expiry_draw_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate_certificate(tmp_path)
    monkeypatch.chdir(tmp_path)
    server = ServerConfig(https={})
    expiry = NativeServer.certificate_expiry(server)
    assert expiry is not None
    expires = datetime.fromtimestamp(expiry, UTC)
    replace = "Run `ceres generate certificate --force` to replace it."

    assert _expiry_warning(server, expires - timedelta(days=30)) is None
    assert _expiry_warning(server, expires - timedelta(days=10)) == (
        f"The HTTPS certificate .ceres/tls/server.crt expires on {expires:%Y-%m-%d}, "
        f"in 10 days. {replace}"
    )
    assert _expiry_warning(server, expires - timedelta(hours=3)) == (
        f"The HTTPS certificate .ceres/tls/server.crt expires on {expires:%Y-%m-%d}, "
        f"in 1 day. {replace}"
    )
    assert _expiry_warning(server, expires + timedelta(seconds=1)) == (
        f"The HTTPS certificate .ceres/tls/server.crt expired on {expires:%Y-%m-%d}. {replace}"
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


async def test_the_server_check_passes_a_generated_certificate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _generate_certificate(tmp_path)
    monkeypatch.chdir(tmp_path)

    config = await Config.load({"server": {"https": {}}}, checks=(ConfigCheckType.SERVER,))

    assert config.server.https is not None


def test_a_dev_run_serves_plain_http_in_place_of_https() -> None:
    server = ServerConfig(https={"port": 8443}, http={"port": 8080, "redirect": True})

    dev = _dev_listener(server, 9000)

    assert dev.https is None
    assert dev.http == ServerHTTPConfig(port=9000)


def test_a_dev_run_of_an_https_only_project_gains_an_http_listener() -> None:
    dev = _dev_listener(ServerConfig(https={}), 9000)

    assert dev.https is None
    assert dev.http == ServerHTTPConfig(port=9000)


def test_a_dev_run_moves_the_http_listener() -> None:
    dev = _dev_listener(ServerConfig(http={"port": 8080}), 9000)

    assert dev.https is None
    assert dev.http == ServerHTTPConfig(port=9000)


def test_a_dev_run_of_a_section_without_listeners_gains_an_http_one() -> None:
    dev = _dev_listener(ServerConfig(), 9000)

    assert dev.https is None
    assert dev.http == ServerHTTPConfig(port=9000)
