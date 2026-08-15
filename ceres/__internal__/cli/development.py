"""Development affordances the CLI offers only when it is running from a source checkout."""

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

from ceres.__internal__.cli.shared import write

if TYPE_CHECKING:
    from ceres.config import Config

_PACKAGE_ROOT: Final = Path(__file__).parent.parent.parent.parent
"""The directory the `ceres` package sits in, which is the repository root in a source checkout."""


def is_development_build() -> bool:
    """Whether this package is being run from a source checkout rather than an installed wheel.

    A wheel installs the package alone, so the project file beside it is what tells the two
    apart.

    Returns:
        True when the package sits in a source checkout.
    """
    return (_PACKAGE_ROOT / "pyproject.toml").is_file()


def find_console_source(source: Path) -> Path:
    """Locate the console within a Ceres source tree.

    Args:
        source: Root of the Ceres source tree.

    Returns:
        The console directory.

    Raises:
        ValueError: If `source` does not look like a Ceres source tree.
    """
    console = source.expanduser().resolve() / "console"
    if not (console / "package.json").is_file():
        raise ValueError(f'"{source}" is not a Ceres source tree, no console/package.json in it.')

    return console


def _free_port() -> int:
    """Ask the operating system for a port nothing is listening on.

    Returns:
        A port number that was free a moment ago.
    """
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class DevelopmentPorts(NamedTuple):
    """Where the engine and the console's dev server each listen."""

    engine: int
    console: int


def assign_ports(config: Config, console_port: int | None) -> DevelopmentPorts:
    """Decide which port the engine and the dev console each take, moving the engine if needed.

    Without a console port the dev console stands in for the built-in one, taking the configured
    port so the address in the browser does not change, and the engine moves to a free port
    behind it. With one, both consoles are served and neither moves.

    Args:
        config: The loaded configuration, whose server section is replaced when the engine moves.
        console_port: Port to serve the dev console on, or None to take the engine's.

    Returns:
        The port each one listens on.
    """
    from ceres.config import ServerConfig
    from ceres.data import to_dict

    configured = config.server.port or 8080
    if console_port is not None:
        return DevelopmentPorts(engine=configured, console=console_port)

    # The port field is not writable, the section being a native object, so the whole section is
    # rebuilt around the new port and the rest of it carried across.
    engine_port = _free_port()
    config.server = ServerConfig(**{**to_dict(config.server), "port": engine_port})
    return DevelopmentPorts(engine=engine_port, console=configured)


@contextlib.asynccontextmanager
async def console_dev_server(source: Path | None, ports: DevelopmentPorts) -> AsyncIterator[None]:
    """Run the console's dev server alongside the engine for as long as the engine runs.

    The dev server proxies API calls through to the engine and holds its websockets straight to
    it, so it is told where the engine ended up rather than assuming the default port.

    Args:
        source: Root of the Ceres source tree, or None to run nothing.
        ports: Where the engine and the dev console each listen.

    Yields:
        None, once the dev server has been spawned.

    Raises:
        ValueError: If `source` does not look like a Ceres source tree.
        RuntimeError: If npm is not installed.
    """
    if source is None:
        yield
        return

    # Imported here rather than at module scope, nothing outside this development-only path
    # needing it, and the CLI pays for every import on every invocation.
    import shutil

    console = find_console_source(source)
    if shutil.which("npm") is None:
        raise RuntimeError(
            "npm was not found on PATH, and the console's dev server is an npm project. "
            "Install Node.js, which npm comes with, from https://nodejs.org or a package "
            "manager, then run this again."
        )

    environment = {
        **os.environ,
        "NUXT_PORT": str(ports.console),
        # Read by the dev proxy for API calls and by the console itself for websockets, which
        # the proxy cannot upgrade and which therefore go straight to the engine.
        "CERES_API_PORT": str(ports.engine),
        "VITE_CERES_API_PORT": str(ports.engine),
    }
    process = await asyncio.create_subprocess_exec(
        "npm", "run", "dev", cwd=console, env=environment
    )
    write(f"Console dev server on port {ports.console}, engine on {ports.engine}.")

    try:
        yield
    finally:
        # Terminated rather than cancelled, the dev server being a child process that outlives
        # this task otherwise and holds its port against the next run.
        with contextlib.suppress(ProcessLookupError):
            process.terminate()

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)
