"""The engine host process.

The `ceres` binary owns the command line. It spawns this module to load the engine or
validate the configuration, passing one JSON payload argument in place of arguments to
parse:

- `config`: absolute path of the project configuration file.
- `addresses`: component address selector strings to start on launch.
- `check`: when true, validate the configuration with all checks and exit.
- `server_port`: when set, the engine's server binds this port instead of the configured
  one, which is how a console dev server stands in front of it.
"""

# ruff: disable[T201] # Allow print statements.

import asyncio
import json
import os
import signal
import sys
import warnings
from asyncio import CancelledError
from asyncio import Event as AsyncEvent
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ceres.__internal__.utilities.exceptions import trace
from ceres.address import AddressSelector
from ceres.concurrency import el, race
from ceres.data import to_json
from ceres.error import ComponentCombinedError, Error


class HostFailed(Exception):
    """A failure with a rendered message, exiting with status 1."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message: str = message


def main() -> int:
    """Run the host from the JSON payload in `sys.argv`.

    Returns:
        The process exit code.
    """
    payload = json.loads(sys.argv[1])

    try:
        return asyncio.run(_execute(payload), loop_factory=el)
    except HostFailed as failure:
        print(failure.message, file=sys.stderr)
        return 1
    except Error as error:
        print(to_json(error, indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt, CancelledError:
        print("Interrupted. Exiting...", file=sys.stderr)
        return 0
    except BrokenPipeError:
        # Output piped into something that stops reading ends where the reader stopped.
        # Standard output is redirected first, because the interpreter flushes it again on
        # the way out and would raise a second time against the same closed pipe.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0


async def _execute(payload: dict[str, Any]) -> int:
    """Dispatch the payload to a check or an engine run."""
    config_path = _enter_project(Path(payload["config"]))
    if payload["check"]:
        return await _check(config_path)

    return await _run(config_path, payload["addresses"], payload["server_port"])


def _enter_project(config_path: Path) -> Path:
    """Move into the project directory and put it on the import path.

    Components import from the project directory, so it becomes the working directory and
    the first import path entry. Further directory changes are disabled, because a
    component moving the process would break every relative path the engine holds.

    Args:
        config_path: Path of the project configuration file.

    Returns:
        The absolute configuration path.
    """
    config_path = config_path.absolute()
    os.chdir(config_path.parent)
    sys.path.insert(0, str(config_path.parent))

    def disabled_chdir(*args: Any, **kwargs: Any) -> None:
        warnings.warn("Changing directory is disabled while running Ceres.")

    os.chdir = disabled_chdir
    return config_path


async def _check(config_path: Path) -> int:
    """Validate the configuration with every check enabled.

    Args:
        config_path: Path of the project configuration file.

    Returns:
        The process exit code.

    Raises:
        HostFailed: If the configuration fails to load or validate.
    """
    from ceres.config import Config, ConfigCheckType

    try:
        await Config.load(config_path, checks=ConfigCheckType.all())
    except Error as error:
        raise HostFailed(f"Failed to load configuration. {to_json(error, indent=2)}")

    print("All checks passed.", file=sys.stderr)
    return 0


async def _run(config_path: Path, addresses: Sequence[str], server_port: int | None) -> int:
    """Load and run the engine until it stops or a signal asks it to.

    Args:
        config_path: Path of the project configuration file.
        addresses: Component address selector strings to start on launch.
        server_port: Port the engine's server binds instead of the configured one.

    Returns:
        The process exit code.

    Raises:
        HostFailed: If the engine fails to load or start.
    """
    from ceres.engine import Engine

    _set_process_name("ceres")

    try:
        address = AddressSelector(addresses) if addresses else None
    except ValueError as error:
        raise HostFailed(str(error))

    try:
        engine = Engine()
        try:
            await engine.load(config_path)
        except Error as error:
            # Structured errors carry an actionable message, show it instead of a dump.
            message = getattr(error, "message", None) or getattr(error, "reason", None)
            if isinstance(message, str):
                raise HostFailed(f"Failed to load engine. {message}")

            if isinstance(error, ComponentCombinedError):
                count = len(error.errors)
                raise HostFailed(
                    f"Failed to load engine. {count} component error(s) occurred, "
                    "see the log output above."
                )

            raise HostFailed(
                f"Failed to load engine with current configuration. {to_json(error, indent=2)}"
            )

        # Applied before the engine starts, since it binds the server section as loaded.
        # The port field is not writable, the section being a native object, so the
        # section is replaced rather than edited.
        if server_port is not None:
            from ceres.data import replace

            engine.config.server = replace(engine.config.server, port=server_port)

        exiting = AsyncEvent()

        async def serve() -> None:
            engine.start()
            if address is not None:
                for component in engine.get_components(address):
                    component.system.start()

            try:
                await race(engine.wait_until_stopped(), exiting.wait())
            finally:
                await engine.stop()

        def handle_exit_signal(*args: Any, **kwargs: Any) -> None:
            exiting.set()

        with _signal_handler([signal.SIGINT, signal.SIGTERM], handle_exit_signal):
            await serve()
    except HostFailed:
        raise
    except Exception as exception:
        message = getattr(exception, "message", None) or getattr(exception, "reason", None)
        if isinstance(exception, Error) and isinstance(message, str):
            raise HostFailed(f"Engine startup failed. {message}")

        raise HostFailed(f"Engine startup failed. {trace(exception)}")

    return 0


@contextmanager
def _signal_handler(signums: Sequence[int], handler: Callable[..., Any]) -> Iterator[None]:
    """Install a signal handler for the given signals, restoring the originals on exit.

    Args:
        signums: The signal numbers to intercept.
        handler: The handler to install for each signal.

    Yields:
        Nothing. The original handlers are restored when the context exits.
    """
    originals = {signum: signal.getsignal(signum) for signum in signums}
    for signum in signums:
        signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            if original is not None:
                signal.signal(signum, original)


def _set_process_name(name: str) -> None:
    """Set the OS-visible process name using `setproctitle`, ignoring failures.

    Args:
        name: The desired process name.
    """
    try:
        from setproctitle import setproctitle

        setproctitle(name)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
