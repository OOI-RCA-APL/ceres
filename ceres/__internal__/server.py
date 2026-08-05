import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Final, override

from ceres.concurrency import concurrently
from ceres.data import DataObject, uuid4
from ceres.tasklet import Tasklet

if TYPE_CHECKING:
    from ceres.__internal__.core import NativeServer as Native
    from ceres.__internal__.project import LoadedProject
    from ceres.config import ServerConfig
    from ceres.engine import Engine

CONSOLE = Path(__file__).parent.parent / "static" / "console"
"""Where the built console assets live."""


class CLIServerInfo(DataObject):
    """JSON-serializable record of a running CLI server's port and authentication token."""

    port: int
    token: str


class Server(Tasklet):
    """Run the engine's native HTTP servers.

    A control server is always bound on an ephemeral loopback port with token
    authentication, and when the configuration names a public port a second server serves
    the API and console there, with TLS when the `ssl` section provides it. Both reach the
    engine through one host object.
    """

    __slots__ = (
        "_engine",
        "_project",
        "_config",
        "_cli_port",
        "_cli_token",
        "_native_cli",
        "_native_web",
        "_web_port",
    )

    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        self._engine: Final = engine
        self._project: Final = project
        self._config: Final = config
        self._cli_port: int | None = None
        self._web_port: int | None = None
        self._cli_token: str | None = None
        self._native_cli: Native | None = None
        self._native_web: Native | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def host(self) -> str:
        return self._config.host

    @property
    def port(self) -> int | None:
        """The port the web server bound, falling back to the configured one.

        A configured `0` asks the operating system for a free port, so the bound one is
        the only answer that means anything to a caller.
        """
        if self._web_port is not None:
            return self._web_port

        return self._config.port

    @property
    def bind(self) -> str | None:
        if self.port is None:
            return None

        return f"{self.host}:{self.port}"

    @property
    def cli_host(self) -> str:
        return "localhost"

    @property
    def cli_port(self) -> int | None:
        return self._cli_port

    @property
    def cli_bind(self) -> str | None:
        if self.cli_port is None:
            return None

        return f"{self.cli_host}:{self.cli_port}"

    @override
    async def __run__(self) -> None:
        self._cli_token = str(uuid4())

        # Operations register on import, so the module has to load before anything serves.
        import ceres.__internal__.app.operations  # noqa: F401
        from ceres.__internal__.app.host import Host
        from ceres.__internal__.core import NativeServer

        host = Host(self._engine)

        # Record requests inside the native filter subset serve straight from the store,
        # never crossing into Python, so the server takes the database's reader when
        # the backend supports one.
        records = self._engine.database._reader()

        # The CLI server is loopback-only. Its token grants full privileges, and everything
        # that talks to it (the CLI, the server info file scheme) is local by design.
        self._native_cli = NativeServer.cli(host, self._config, self._cli_token, records)
        self._cli_port = self._native_cli.port

        if self._config.port is not None:
            console = CONSOLE
            self._native_web = NativeServer.web(
                host,
                self._config,
                console,
                _favicon(self._engine, ".ico", console),
                _favicon(self._engine, ".png", console),
                _favicon(self._engine, ".svg", console),
                records,
            )
            self._web_port = self._native_web.port

        # The info file records the port the control server actually bound.
        self._project.write_cli_server_info(
            CLIServerInfo(port=self._cli_port, token=self._cli_token)
        )

        try:
            await concurrently(_serve(self._native_cli), _serve(self._native_web))
        finally:
            self._native_cli = None
            self._native_web = None
            try:
                self._project.delete_cli_server_info()
            except Exception:
                traceback.print_exc()

    @override
    async def __stop__(self) -> None:
        for server in (self._native_cli, self._native_web):
            if server is not None:
                server.stop()


async def _serve(server: Native | None) -> None:
    """Run one native server to completion, doing nothing when there is none.

    A native server's `serve` answers a future rather than a coroutine, and a task group
    schedules coroutines, so awaiting it inside one is what makes it schedulable.
    """
    if server is not None:
        await server.serve()


def _favicon(engine: Engine, suffix: str, console: Path) -> Path:
    """Resolve one favicon, the configured override winning when its suffix matches."""
    configured = engine.config.console.favicon
    if configured is not None and configured.suffix == suffix:
        return configured

    return console / f"favicon{suffix}"
