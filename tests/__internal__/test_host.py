"""The engine host's dev listener and its certificate expiry warning."""

from __future__ import annotations

import json
import subprocess
import sys
import sysconfig
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ceres.__internal__.core import NativeServer
from ceres.__internal__.host import (
    _authority_warning,
    _certificate_plan,
    _check,
    _dev_listener,
    _expiry_warning,
)
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
    status = NativeServer.certificate_status(server)
    assert status is not None
    expiry, plan, warning = status
    assert expiry is not None
    assert plan is None
    assert warning is None
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


def test_engine_startup_logs_the_expiry_warning(tmp_path: Path) -> None:
    """The host logs the warning once the engine loads, before it starts serving.

    The host runs until a signal stops it, so it runs as its own process, stopped once the
    engine reports having started.
    """
    (tmp_path / "ceres.yaml").write_text(
        "server:\n  bind: 127.0.0.1\n  https:\n    port: 0\n"
        f"database:\n  type: sqlite\n  path: {tmp_path / 'records.sqlite'}\n"
    )
    subprocess.run(
        [CERES, "generate", "certificate", "--days", "3"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    payload = {"config": str(tmp_path / "ceres.yaml"), "addresses": [], "check": False}
    host = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from ceres.__internal__.host import main; sys.exit(main())",
            json.dumps(payload | {"server_port": None}),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # A backstop against a host that never starts, which would otherwise hang the read.
    watchdog = threading.Timer(60, host.kill)
    watchdog.start()
    output: list[str] = []
    try:
        assert host.stdout is not None
        for line in host.stdout:
            output.append(line)
            if '"type":"started"' in "".join(output).replace("\n", "").replace(" ", ""):
                break
    finally:
        host.terminate()
        host.wait()
        watchdog.cancel()

    # Log lines wrap to the terminal width, so the words are compared without the breaks.
    logged = " ".join("".join(output).split())
    # Validity starts an hour back and spans the days asked for.
    expires = f"{datetime.now(UTC) - timedelta(hours=1) + timedelta(days=3):%Y-%m-%d}"
    assert (
        f"[WARNING] [~] The HTTPS certificate .ceres/tls/server.crt expires on {expires}, "
        "in 3 days. Run `ceres generate certificate --force` to replace it."
    ) in logged, logged
    assert logged.count("The HTTPS certificate") == 1


def test_no_https_listener_draws_no_warning() -> None:
    assert _expiry_warning(ServerConfig(http={"port": 8080}), datetime.now(UTC)) is None
    assert _certificate_plan(ServerConfig(http={"port": 8080})) is None


def test_managed_certificates_draw_no_expiry_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    server = ServerConfig(https={"certificate": "auto"})

    assert _expiry_warning(server, datetime.now(UTC) + timedelta(days=3650)) is None


EXPIRED_AUTHORITY = """\
-----BEGIN CERTIFICATE-----
MIIBoDCCAUagAwIBAgIUK7PuFwbBkHMPRYodhZX0G0xnHfMwCgYIKoZIzj0EAwIw
HDEaMBgGA1UEAwwRRXhwaXJlZCBhdXRob3JpdHkwHhcNMTkwMTAxMDAwMDAwWhcN
MjAwMTAxMDAwMDAwWjAcMRowGAYDVQQDDBFFeHBpcmVkIGF1dGhvcml0eTBZMBMG
ByqGSM49AgEGCCqGSM49AwEHA0IABL8KEoUrxmLpt3kX8bNAlDhmw1nVm1Lgjak/
taQAA5VXSFRnS0XxQelet6TgN6yZIWQx6dB6fl1FHcmY/H/ujbOjZjBkMB0GA1Ud
DgQWBBSDgXLn7VJJwjhLIrCIlDKPrNTWjDAfBgNVHSMEGDAWgBSDgXLn7VJJwjhL
IrCIlDKPrNTWjDASBgNVHRMBAf8ECDAGAQH/AgEAMA4GA1UdDwEB/wQEAwICBDAK
BggqhkjOPQQDAgNIADBFAiBB4IwQjZyeXto2C1q0ehHiIIartSH6r9+PXyvtX/Qc
owIhAMD26aOSB6A2EngNFNstozgWBUFBv2NGSzZMVnlqAsP0
-----END CERTIFICATE-----
"""
"""A P-256 certificate authority valid through 2019 only, so it stays expired."""

EXPIRED_AUTHORITY_KEY = """\
-----BEGIN PRIVATE KEY-----
MIGHAgEAMBMGByqGSM49AgEGCCqGSM49AwEHBG0wawIBAQQgnGB4oDzSU54YnyQe
KyWo6/mXeoFdXLq9yMhc92AOCdShRANCAAS/ChKFK8Zi6bd5F/GzQJQ4ZsNZ1ZtS
4I2pP7WkAAOVV0hUZ0tF8UHpXrek4DesmSFkMenQen5dRR3JmPx/7o2z
-----END PRIVATE KEY-----
"""
"""The throwaway key of `EXPIRED_AUTHORITY`, which signs nothing anyone trusts."""


async def test_the_check_warns_of_an_expired_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ca.crt").write_text(EXPIRED_AUTHORITY)
    (tmp_path / "ca.key").write_text(EXPIRED_AUTHORITY_KEY)
    https = {"certificate": {"auto": {"ca": {"path": "ca.crt", "key": "ca.key"}}}}
    (tmp_path / "ceres.yaml").write_text(json.dumps({"server": {"https": https}}))
    warning = (
        "The certificate authority ca.crt expired on 2020-01-01, so clients no longer trust the "
        "certificates it signs. Ceres never renews an authority. Replace it at the paths "
        "`auto.ca` names, and trust the new one on each client."
    )

    assert _authority_warning(ServerConfig(https=https)) == warning
    assert await _check(tmp_path / "ceres.yaml") == 0
    assert warning in capsys.readouterr().err
    assert not (tmp_path / ".ceres").exists()


def test_the_check_reports_what_startup_issues_without_writing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert _certificate_plan(ServerConfig(https={"certificate": "auto"})) == (
        "Startup creates the certificate authority .ceres/tls/ca.crt and issues the HTTPS "
        "certificate .ceres/tls/server.crt with it."
    )
    assert not (tmp_path / ".ceres").exists()


async def test_the_server_check_refuses_a_missing_supplied_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    https = {"certificate": {"auto": {"ca": {"path": "ca/typo.crt", "key": "ca/typo.key"}}}}

    with pytest.raises(ConfigCombinedError) as raised:
        await Config.load({"server": {"https": https}}, checks=(ConfigCheckType.SERVER,))

    [error] = raised.value.errors
    assert isinstance(error, ConfigValidationError)
    [problem] = error.problems
    assert problem.location == ["server", "https"]
    assert problem.message == (
        "ca/typo.crt does not exist. Ceres never creates the certificate authority `auto.ca` names."
    )
    assert not (tmp_path / "ca").exists()
    assert not (tmp_path / ".ceres").exists()


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
        ".ceres/tls/server.crt does not exist. Run `ceres generate certificate` to write the "
        "certificate .ceres/tls/server.crt and key .ceres/tls/server.key, or set "
        "`certificate: auto` under `server.https` for Ceres to manage them."
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
