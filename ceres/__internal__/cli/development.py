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


def _free_port(host: str) -> int:
    """Ask the operating system for a port nothing is listening on.

    Args:
        host: The host the caller goes on to bind, probed so a port taken on it alone is
            not reported as free.

    Returns:
        A port number that was free a moment ago.
    """
    import socket

    with socket.socket() as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


class DevelopmentAddresses(NamedTuple):
    """Where the engine and the console's dev server each listen."""

    host: str
    engine: int
    console: int


def assign_addresses(config: Config, console_port: int | None) -> DevelopmentAddresses:
    """Decide which port the engine and the dev console each take, moving the engine if needed.

    Without a console port the dev console stands in for the built-in one, taking the configured
    port so the address in the browser does not change, and the engine moves to a free port
    behind it. With one, both consoles are served and neither moves.

    Args:
        config: The loaded configuration, whose server section is replaced when the engine moves.
        console_port: Port to serve the dev console on, or None to take the engine's.

    Returns:
        The host and port each one listens on.
    """
    from ceres.data import replace

    host = config.server.host
    configured = config.server.port or 8080
    if console_port is not None:
        return DevelopmentAddresses(host=host, engine=configured, console=console_port)

    # The port field is not writable, the section being a native object, so the section is
    # replaced rather than edited.
    engine_port = _free_port(host)
    config.server = replace(config.server, port=engine_port)
    return DevelopmentAddresses(host=host, engine=engine_port, console=configured)


@contextlib.asynccontextmanager
async def console_dev_server(
    source: Path | None, addresses: DevelopmentAddresses
) -> AsyncIterator[None]:
    """Run the console's dev server alongside the engine for as long as the engine runs.

    The dev server proxies API calls through to the engine and holds its websockets straight to
    it, so it is told where the engine ended up rather than assuming the default port.

    Args:
        source: Root of the Ceres source tree, or None to run nothing.
        addresses: Where the engine and the dev console each listen.

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
        # Bound where the engine's own server would be, standing in for it. Nuxt otherwise
        # defaults to `localhost`, which Node resolves to the IPv6 loopback alone.
        "NUXT_HOST": addresses.host,
        "NUXT_PORT": str(addresses.console),
        # Read by the dev proxy for API calls and by the console itself for websockets, which
        # the proxy cannot upgrade and which therefore go straight to the engine.
        "CERES_API_PORT": str(addresses.engine),
        "VITE_CERES_API_PORT": str(addresses.engine),
    }
    process = await asyncio.create_subprocess_exec(
        "npm", "run", "dev", cwd=console, env=environment
    )
    write(f"Console dev server on port {addresses.console}, engine on {addresses.engine}.")

    try:
        yield
    finally:
        # Terminated rather than cancelled, the dev server being a child process that outlives
        # this task otherwise and holds its port against the next run.
        with contextlib.suppress(ProcessLookupError):
            process.terminate()

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)
