from __future__ import annotations

import socket
import traceback
from contextlib import closing
from typing import Any, Final, override

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres.data import ImmutableDataObject, uuid4
from ceres.tasklet import Tasklet
from ceres.threading import spawn

with lazy_imports(__name__):
    from granian.constants import Interfaces
    from granian.server.embed import Server as Granian

    from ceres._internal.app import App
    from ceres._internal.project import LoadedProject
    from ceres.config import ServerConfig
    from ceres.engine import Engine


class CLIServerInfo(ImmutableDataObject):
    port: int
    token: str


class Server(Tasklet):
    def __init__(self, engine: Engine, project: LoadedProject, config: ServerConfig) -> None:
        self.__engine: Final = engine
        self.__project: Final = project
        self.__config: Final = config

        self.__cli_port: int | None = None
        self.__cli_token: str | None = None
        self.__granian_cli: Granian | None = None
        self.__granian_web: Granian | None = None

    @property
    def config(self) -> ServerConfig:
        return self.__config

    @property
    def host(self) -> str:
        return self.__config.host

    @property
    def port(self) -> int | None:
        return self.__config.port

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
        return self.__cli_port

    @property
    def cli_bind(self) -> str | None:
        if self.cli_port is None:
            return None

        return f"{self.cli_host}:{self.cli_port}"

    @override
    async def __run__(self) -> None:
        self.__cli_port = await self.__get_free_port()
        self.__cli_token = str(uuid4())

        self.__project.write_cli_server_info(
            CLIServerInfo(
                port=self.__cli_port,
                token=self.__cli_token,
            )
        )

        ssl = self.__config.ssl
        shared: dict[str, Any] = {
            "log_enabled": False,
            "interface": Interfaces.ASGI,
            "ssl_key": ssl.key if ssl else None,
            "ssl_cert": ssl.cert if ssl else None,
            "ssl_key_password": ssl.key_password if ssl else None,
        }

        self.__granian_cli = Granian(
            App(self.__engine, None, self.__cli_token),
            address=self.__config.host,
            port=self.__cli_port,
            **shared,
        )

        if self.__config.port is not None:
            self.__granian_web = Granian(
                App(self.__engine),
                address=self.__config.host,
                port=self.__config.port,
                **shared,
            )

        try:
            await util.concurrently(
                self.__granian_cli.serve(),
                self.__granian_web.serve() if self.__granian_web is not None else None,
            )
        finally:
            self.__granian_cli = None
            self.__granian_web = None
            try:
                self.__project.delete_cli_server_info()
            except Exception:
                traceback.print_exc()

    @override
    async def __stop__(self) -> None:
        cli = self.__granian_cli
        if cli is not None:
            cli.stop()

        web = self.__granian_web
        if web is not None:
            web.stop()

    async def __get_free_port(self) -> int:
        def run():
            with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as stream:
                stream.bind(("", 0))
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                return stream.getsockname()[1]

        return await spawn(run)
