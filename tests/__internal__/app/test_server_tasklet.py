"""The server tasklet that runs the native servers for a loaded engine.

The native server's `serve` answers a future rather than a coroutine, and the tasklet
schedules it in a task group, which takes coroutines alone. Nothing else covers that
crossing, because the other native server tests await `serve` directly, so this is where
a server that binds its port and then dies immediately would show.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ceres import Engine
from ceres.__internal__.project import LoadedProject

if TYPE_CHECKING:
    from pathlib import Path


async def test_the_server_tasklet_keeps_the_cli_server_running(tmp_path: Path) -> None:
    """A loaded engine binds its CLI server, records it, and stays up."""
    # The database path is absolute because a relative one resolves against the working
    # directory rather than the configuration's own.
    (tmp_path / "ceres.yaml").write_text(
        f"components: []\ndatabase:\n  type: sqlite\n  path: {tmp_path / 'records.sqlite'}\n"
    )

    failures: list[BaseException] = []
    engine = Engine()
    engine._on_server_exception = lambda server, exception: failures.append(exception)  # type: ignore[method-assign]
    await engine.load(tmp_path / "ceres.yaml", checks=())

    try:
        server = engine.server
        assert server is not None
        assert server.cli_port is not None

        # The info file is how the CLI finds the port, and the tasklet deletes it on the
        # way out, so it standing after a moment is the server still serving.
        info = LoadedProject(engine.config_path, engine.config).cli_server_info_path
        assert info.exists()
        await asyncio.sleep(0.2)
        assert info.exists()
        assert server.running
        assert failures == []
    finally:
        await server.stop()
        await engine.database.dispose()
