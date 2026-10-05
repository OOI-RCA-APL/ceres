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
    authentication. The `https` listener serves the API and console over TLS, and the
    `http` listener serves them over plain HTTP, or with `redirect` set answers every
    request with a temporary redirect to the `https` one. Every server reaches the engine
    through one host object.
    """

    __slots__ = (
        "_engine",
        "_project",
        "_config",
        "_cli_port",
        "_cli_token",
        "_native_cli",
        "_native_https",
        "_native_http",
    )

    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        self._engine: Final = engine
        self._project: Final = project
        self._config: Final = config
        self._cli_port: int | None = None
        self._cli_token: str | None = None
        self._native_cli: Native | None = None
        self._native_https: Native | None = None
        self._native_http: Native | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def host(self) -> str:
        return self._config.bind

    @property
    def https_port(self) -> int | None:
        """The port the HTTPS listener bound, falling back to the configured one.

        A configured `0` asks the operating system for a free port so the bound one is
        the only answer that means anything to a caller.
        """
        if self._native_https is not None:
            return self._native_https.port

        https = self._config.https
        return None if https is None else https.port

    @property
    def http_port(self) -> int | None:
        """The port the plain HTTP listener bound, falling back to the configured one."""
        if self._native_http is not None:
            return self._native_http.port

        http = self._config.http
        return None if http is None else http.port

    @property
    def port(self) -> int | None:
        """The port serving the console, the HTTPS listener when there is one."""
        if self._config.https is not None:
            return self.https_port

        return self.http_port

    @property
    def listeners(self) -> list[str]:
        """One line per public listener naming its address and role, for the startup log."""
        lines = []
        if self._config.https is not None:
            lines.append(f"HTTPS web server listening on {self.host}:{self.https_port}.")

        http = self._config.http
        if http is not None:
            role = "redirect" if http.redirect else "web"
            lines.append(f"HTTP {role} server listening on {self.host}:{self.http_port}.")

        return lines

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

        # Operations register on import so the module has to load before anything serves.
        import ceres.__internal__.app.operations  # noqa: F401
        from ceres.__internal__.app.host import Host
        from ceres.__internal__.core import NativeServer

        host = Host(self._engine)

        # Record requests inside the native filter subset serve straight from the store,
        # never crossing into Python so the server takes the database's reader.
        records = self._engine.database._reader()

        # The CLI server is loopback-only. Its token grants full privileges, and everything
        # that talks to it (the CLI, the server info file scheme) is local by design.
        self._native_cli = NativeServer.cli(host, self._config, self._cli_token, records)
        self._cli_port = self._native_cli.port

        https = self._config.https
        http = self._config.http
        serves_https = https is not None
        serves_http = http is not None and not http.redirect
        if serves_https or serves_http:
            console = CONSOLE
            # The bundle is a build artifact, so a source checkout has none until something
            # builds one. The server stands a placeholder page in for it either way.
            if not (console / "index.html").is_file():
                self._engine.log.warning(
                    "The web console is not built. A placeholder web page will be shown instead. "
                    "Run `make console` in the Ceres checkout to build it."
                )

            def web(*, tls: bool) -> Native:
                return NativeServer.web(
                    host,
                    self._config,
                    console,
                    _favicon(self._engine, ".ico", console),
                    _favicon(self._engine, ".png", console),
                    _favicon(self._engine, ".svg", console),
                    tls=tls,
                    records=records,
                )

            if serves_https:
                self._native_https = web(tls=True)
            if serves_http:
                self._native_http = web(tls=False)

        if self._native_https is not None and http is not None and http.redirect:
            # The redirect targets the bound port, which differs from the configured one
            # when that is `0`.
            self._native_http = NativeServer.redirect(self._config, self._native_https.port)

        # The info file records the port the control server actually bound.
        self._project.write_cli_server_info(
            CLIServerInfo(port=self._cli_port, token=self._cli_token)
        )

        try:
            await concurrently(
                _serve(self._native_cli),
                _serve(self._native_https),
                _serve(self._native_http),
            )
        finally:
            self._native_cli = None
            self._native_https = None
            self._native_http = None
            try:
                self._project.delete_cli_server_info()
            except Exception:
                traceback.print_exc()

    @override
    async def __stop__(self) -> None:
        for server in (self._native_cli, self._native_https, self._native_http):
            if server is not None:
                server.stop()


async def _serve(server: Native | None) -> None:
    """Run one native server to completion, doing nothing when there is none.

    A native server's `serve` answers a future rather than a coroutine, and a task group
    schedules coroutines so awaiting it inside one makes it schedulable.
    """
    if server is not None:
        await server.serve()


def _favicon(engine: Engine, suffix: str, console: Path) -> Path:
    """Resolve one favicon, the configured override winning when its suffix matches."""
    configured = engine.config.console.favicon
    if configured is not None and configured.suffix == suffix:
        return configured

    return console / f"favicon{suffix}"
