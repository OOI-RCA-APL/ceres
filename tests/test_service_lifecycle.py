"""The systemd service lifecycle, driven against a real user manager.

Gated behind `CERES_SERVICE_TEST` since it manages a unit on the host's own systemd,
which only CI provides predictably. The child environment drops `XDG_RUNTIME_DIR` so the
commands must reach the user bus on their own, the failure a session-less shell produces.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("CERES_SERVICE_TEST") != "1",
    reason="Drives the host's systemd user manager, enabled in CI.",
)

_SERVICE_NAME = "ceres-service-test"


def _run(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key != "XDG_RUNTIME_DIR"}
    return subprocess.run(
        [sys.executable, "-m", "ceres", *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=environment,
    )


def _state(cwd: Path) -> str:
    status = _run("service", "status", cwd=cwd)
    assert status.returncode == 0, status.stdout + status.stderr
    return "Running" if "Running" in status.stdout else "Stopped"


def _diagnostics(cwd: Path) -> str:
    """The unit's own story for a failure message, since the state alone says nothing."""
    status = _run("service", "status", cwd=cwd)
    environment = {key: value for key, value in os.environ.items() if key != "XDG_RUNTIME_DIR"}
    environment["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    pieces = ["The service never reported Running.", status.stdout + status.stderr]
    for command in (
        ["journalctl", "--user", "-u", f"{_SERVICE_NAME}.service", "-n", "10", "--no-pager"],
        ["systemctl", "--user", "is-active", f"{_SERVICE_NAME}.service"],
        ["systemctl", "--user", "status", f"{_SERVICE_NAME}.service", "--no-pager"],
    ):
        report = subprocess.run(command, capture_output=True, text=True, env=environment)
        pieces.append(f"$ {' '.join(command)} -> {report.returncode}")
        pieces.append(report.stdout + report.stderr)

    return "\n".join(pieces)


def test_service_lifecycle(tmp_path: Path) -> None:
    """The service starts, stays up, and stops, all without a session's own bus."""
    (tmp_path / "ceres.yaml").write_text(
        "components: []\n"
        "database:\n  type: sqlite\n  path: records.sqlite\n"
        f"service:\n  name: {_SERVICE_NAME}\n"
    )
    unit = Path.home() / ".config/systemd/user" / f"{_SERVICE_NAME}.service"

    try:
        started = _run("service", "start", cwd=tmp_path)
        assert started.returncode == 0, started.stdout + started.stderr
        assert unit.exists()

        deadline = time.monotonic() + 60
        while _state(tmp_path) != "Running":
            assert time.monotonic() < deadline, _diagnostics(tmp_path)
            time.sleep(1)

        # Still up moments later, so a crash looping under Restart=always cannot pass as
        # a running engine.
        time.sleep(3)
        assert _state(tmp_path) == "Running"
    finally:
        stopped = _run("service", "stop", cwd=tmp_path)

    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert _state(tmp_path) == "Stopped"
    assert not unit.exists()
