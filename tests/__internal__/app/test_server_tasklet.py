"""The server tasklet that runs the native servers for a loaded engine.

The native server's `serve` answers a future rather than a coroutine, and the tasklet
schedules it in a task group, which takes coroutines alone. Nothing else covers that
crossing, because the other native server tests await `serve` directly, so this is where
a server that binds its port and then dies immediately would show. Both the CLI server
and the web one go through it, so both are tested here.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import httpx

from ceres import Engine
from ceres.__internal__.project import LoadedProject

if TYPE_CHECKING:
    from pathlib import Path


async def _load(tmp_path: Path, failures: list[BaseException], *, web: bool) -> Engine:
    """Load an engine from a written configuration, capturing any server failure."""
    # The database path is absolute because a relative one resolves against the working
    # directory rather than the configuration's own.
    server = "server:\n  port: 0\n" if web else ""
    (tmp_path / "ceres.yaml").write_text(
        f"components: []\n{server}"
        f"database:\n  type: sqlite\n  path: {tmp_path / 'records.sqlite'}\n"
    )

    engine = Engine()
    engine._on_server_exception = lambda server, exception: failures.append(exception)  # type: ignore[method-assign]
    await engine.load(tmp_path / "ceres.yaml", checks=())
    return engine


async def test_the_server_tasklet_keeps_the_cli_server_running(tmp_path: Path) -> None:
    """A loaded engine binds its CLI server, records it, and stays up."""
    failures: list[BaseException] = []
    engine = await _load(tmp_path, failures, web=False)
    server = engine.server
    assert server is not None

    try:
        assert server.cli_port is not None

        # The info file is how the CLI finds the port, and the tasklet deletes it on the
        # way out, so it standing after a moment is the server still serving.
        config_path = engine.config_path
        assert config_path is not None
        info = LoadedProject(config_path, engine.config).cli_server_info_path
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
    engine = await _load(tmp_path, failures, web=True)
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
