from __future__ import annotations

import socket
import traceback
from contextlib import closing
from typing import Any, Final, override

from granian.constants import Interfaces
from granian.log import LogLevels
from granian.server.embed import Server as GranianServer

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject, uuid4
from ceres.tasklet import Tasklet
from ceres.threading import spawn

with lazy_imports(__name__):
    from ceres._internal.app import App
    from ceres._internal.project import LoadedProject
    from ceres.config import ServerConfig
    from ceres.engine import Engine


class CLIServerInfo(ImmutableDataObject):
    port: int
    token: str


class Server(Tasklet):
    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        self._engine: Final = engine
        self._project: Final = project
        self._config: Final = config

        self._cli_port: int | None = None
        self._cli_token: str | None = None
        self._granian_cli: GranianServer | None = None
        self._granian_web: GranianServer | None = None

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

        shared: dict[str, Any] = {
            "log_level": LogLevels.critical,
            "log_access": False,
            "interface": Interfaces.ASGI,
        }

        cli_app = App(self._engine, None, self._cli_token)
        self._granian_cli = GranianServer(
            cli_app,
            address=self._config.host,
            port=self._cli_port,
            **shared,
        )

        if self._config.port is not None:
            web_app = App(self._engine, None, None)
            self._granian_web = GranianServer(
                web_app,
                address=self._config.host,
                port=self._config.port,
                **shared,
            )

        try:
            await util.concurrently(
                self._granian_cli.serve(),
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
