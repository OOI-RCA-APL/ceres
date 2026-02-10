from __future__ import annotations

import socket
import traceback
from contextlib import closing
from typing import TYPE_CHECKING, Any, Final, override

from ceres._internal import util
from ceres.data import ImmutableDataModel, uuid4
from ceres.tasklet import Tasklet
from ceres.threading import spawn

if TYPE_CHECKING:
    from granian.server.embed import Server as Granian

    from ceres._internal.project import LoadedProject
    from ceres.config import ServerConfig
    from ceres.engine import Engine


class CLIServerInfo(ImmutableDataModel):
    port: int
    token: str


class Server(Tasklet):
    __slots__ = (
        "_engine",
        "_project",
        "_config",
        "_cli_port",
        "_cli_token",
        "_granian_cli",
        "_granian_web",
    )

    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        self._engine: Final = engine
        self._project: Final = project
        self._config: Final = config
        self._cli_port: int | None = None
        self._cli_token: str | None = None
        self._granian_cli: Granian | None = None
        self._granian_web: Granian | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def host(self) -> str:
        return self._config.host

    @property
    def port(self) -> int | None:
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
        self._cli_port = await self._get_free_port()
        self._cli_token = str(uuid4())

        self._project.write_cli_server_info(
            CLIServerInfo(
                port=self._cli_port,
                token=self._cli_token,
            )
        )

        from granian.constants import Interfaces
        from granian.server.embed import Server as Granian

        from ceres._internal.app import App

        shared: dict[str, Any] = {
            "log_enabled": False,
            "interface": Interfaces.ASGI,
        }

        self._granian_cli = Granian(
            App(self._engine, None, self._cli_token),
            address=self._config.host,
            port=self._cli_port,
            **shared,
        )

        if self._config.port is not None:
            ssl = self._config.ssl
            self._granian_web = Granian(
                App(self._engine),
                address=self._config.host,
                port=self._config.port,
                ssl_key=ssl.key if ssl else None,
                ssl_cert=ssl.cert if ssl else None,
                ssl_key_password=ssl.key_password if ssl else None,
                **shared,
            )

        try:
            await util.concurrently(
                self._granian_cli.serve() if self._granian_cli is not None else None,
                self._granian_web.serve() if self._granian_web is not None else None,
            )
        finally:
            self._granian_cli = None
            self._granian_web = None
            try:
                self._project.delete_cli_server_info()
            except Exception:
                traceback.print_exc()

    @override
    async def __stop__(self) -> None:
        cli = self._granian_cli
        if cli is not None:
            cli.stop()

        web = self._granian_web
        if web is not None:
            web.stop()

    async def _get_free_port(self) -> int:
        def run():
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as stream:
                stream.bind(("", 0))
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                return stream.getsockname()[1]

        return await spawn(run)
