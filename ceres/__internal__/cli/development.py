"""Development affordances the CLI offers only when it is running from a source checkout."""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Final

from ceres.__internal__.cli.shared import write

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


@contextlib.asynccontextmanager
async def console_dev_server(source: Path | None) -> AsyncIterator[None]:
    """Run the console's dev server alongside the engine for as long as the engine runs.

    The dev server proxies its own API calls to the engine, so it is started beside the engine
    rather than served through it, and the browser is pointed at the dev server's port.

    Args:
        source: Root of the Ceres source tree, or None to run nothing.

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

    process = await asyncio.create_subprocess_exec("npm", "run", "dev", cwd=console)
    write(f"Console dev server started from {console}.")

    try:
        yield
    finally:
        # Terminated rather than cancelled, the dev server being a child process that outlives
        # this task otherwise and holds its port against the next run.
        with contextlib.suppress(ProcessLookupError):
            process.terminate()

        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=5)
