"""The server tasklet that runs the native servers for a loaded engine.

The native server's `serve` answers a future rather than a coroutine, and the tasklet
schedules it in a task group, which takes coroutines alone. Nothing else covers that
crossing, because the other native server tests await `serve` directly, so this is where
a server that binds its port and then dies immediately would show. The CLI server, the
web one, and the redirect one all go through it, so all are tested here.
"""

from __future__ import annotations

import asyncio
import subprocess
import sysconfig
from collections.abc import Sequence
from functools import partial
from pathlib import Path

import httpx

from ceres import Engine
from ceres.__internal__.host import _dev_listener
from ceres.__internal__.project import LoadedProject
from ceres.config import ConfigCheckType


async def _load(
    tmp_path: Path,
    failures: list[BaseException],
    *,
    server: str = "",
    engine: Engine | None = None,
    checks: Sequence[ConfigCheckType] = (),
) -> Engine:
    """Load an engine from a written configuration, capturing any server failure."""
    # The database path is absolute because a relative one resolves against the working
    # directory rather than the configuration's own.
    (tmp_path / "ceres.yaml").write_text(
        f"components: []\n{server}"
        f"database:\n  type: sqlite\n  path: {tmp_path / 'records.sqlite'}\n"
    )

    engine = engine or Engine()
    engine._on_server_exception = lambda server, exception: failures.append(exception)  # type: ignore[method-assign]
    await engine.load(tmp_path / "ceres.yaml", checks=checks)
    return engine


async def test_the_server_tasklet_keeps_the_cli_server_running(tmp_path: Path) -> None:
    """A loaded engine binds its CLI server, records it, and stays up."""
    failures: list[BaseException] = []
    engine = await _load(tmp_path, failures)
    server = engine.server
    assert server is not None

    try:
        assert server.cli_port is not None

        # The info file is how the CLI finds the port, and the tasklet deletes it on the
        # way out, so it standing after a moment is the server still serving.
        config_path = engine.config_path
        assert config_path is not None
        info = LoadedProject(config_path, engine.config).cli_server_info_path
        assert info == tmp_path / ".ceres" / "server.json"
        assert info.exists()
        await asyncio.sleep(0.2)
        assert info.exists()
        assert server.running
        assert failures == []
    finally:
        await server.stop()
        await engine.database.dispose()


async def test_the_server_tasklet_keeps_the_web_server_answering(tmp_path: Path) -> None:
    """A configured web server binds through the same tasklet and answers requests.

    The web server is the arm nothing else covers through the tasklet, so a request that
    lands is what proves it is really serving rather than only having bound a port.
    """
    failures: list[BaseException] = []
    engine = await _load(tmp_path, failures, server="server:\n  http:\n    port: 0\n")
    server = engine.server
    assert server is not None

    try:
        assert server.port is not None
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server.port}/api/alive")

        assert response.status_code == 200
        assert server.running
        assert failures == []
    finally:
        await server.stop()
        await engine.database.dispose()


async def test_the_http_listener_redirects_to_the_bound_https_one(tmp_path: Path) -> None:
    """With both listeners on ephemeral ports, the redirect names the port HTTPS bound.

    The configured HTTPS port is `0`, so a redirect built from the configuration alone
    would point nowhere.
    """
    (tmp_path / "ceres.yaml").touch()
    ceres = Path(sysconfig.get_path("scripts")) / "ceres"
    subprocess.run(
        [ceres, "generate", "certificate"], cwd=tmp_path, check=True, capture_output=True
    )
    tls = tmp_path / ".ceres" / "tls"
    failures: list[BaseException] = []
    engine = await _load(
        tmp_path,
        failures,
        server=(
            "server:\n  bind: 127.0.0.1\n"
            f"  https:\n    port: 0\n    cert: {tls / 'server.crt'}\n"
            f"    key: {tls / 'server.key'}\n"
            "  http:\n    port: 0\n    redirect: true\n"
        ),
    )
    server = engine.server
    assert server is not None

    try:
        https_port, http_port = server.https_port, server.http_port
        assert https_port and http_port and https_port != http_port
        assert server.port == https_port
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(f"https://127.0.0.1:{https_port}/api/alive")
            assert response.status_code == 200

            response = await client.get(f"http://127.0.0.1:{http_port}/console?tab=1")
            assert response.status_code == 307
            location = f"https://127.0.0.1:{https_port}/console?tab=1"
            assert response.headers["location"] == location

        assert server.listeners == [
            f"HTTPS web server listening on 127.0.0.1:{https_port}.",
            f"HTTP redirect server listening on 127.0.0.1:{http_port}.",
        ]
        assert failures == []
    finally:
        await server.stop()
        await engine.database.dispose()


async def test_an_overridden_server_binds_only_what_the_override_answers(tmp_path: Path) -> None:
    """A development run's listener is the first and only one bound, with no certificate.

    The configuration asks for HTTPS on a privileged port with certificate files that do
    not exist, so binding it even once, or running the server check, would fail.
    """
    failures: list[BaseException] = []
    overridden = Engine()
    overridden._override_server(partial(_dev_listener, port=0))
    engine = await _load(
        tmp_path,
        failures,
        server="server:\n  bind: 127.0.0.1\n  https: {}\n  http:\n    redirect: true\n",
        engine=overridden,
        checks=ConfigCheckType.all(),
    )
    server = engine.server
    assert server is not None

    try:
        assert engine.config.server.https is None
        assert server.https_port is None
        assert server.port is not None
        async with httpx.AsyncClient() as client:
            response = await client.get(f"http://127.0.0.1:{server.port}/api/alive")

        assert response.status_code == 200
        assert server.listeners == [f"HTTP web server listening on 127.0.0.1:{server.port}."]

        # A reload rereads the file, and the override still applies.
        await engine.reload()
        assert engine.server is server
        assert failures == []
    finally:
        await server.stop()
        await engine.database.dispose()
