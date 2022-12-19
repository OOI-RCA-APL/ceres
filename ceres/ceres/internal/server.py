import asyncio
import socket
from asyncio import Task
from typing import TYPE_CHECKING, Any, final

from starlette.types import ASGIApp
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn

from ..config import ServerConfig
from . import logs
from .tasklet import Tasklet

if TYPE_CHECKING:
    from uvicorn.server import Protocols
else:
    Protocols = "Protocols"


@final
class Server(Tasklet):
    def __init__(self, app: ASGIApp, config: ServerConfig) -> None:
        self.__app = app
        self.__config = config
        self.__uvicorn: Uvicorn | None = None

    @property
    def app(self) -> ASGIApp:
        return self.__app

    @property
    def config(self) -> ServerConfig:
        return self.__config

    async def __run__(self) -> None:
        self.__uvicorn = Uvicorn(
            UvicornConfig(
                app=self.app,
                port=self.config.port,
                loop="none",
            )
        )

        await self.__uvicorn.serve()

    async def __stop__(self) -> None:
        if self.__uvicorn is not None:
            await self.__uvicorn.shutdown()
            self.__uvicorn = None


class Uvicorn(BaseUvicorn):
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        async def stop_connection(connection: Protocols) -> None:
            try:
                await connection.close()  # type: ignore
            except Exception:
                connection.shutdown()

        async def stop_task(task: Task[Any]) -> None:
            task.cancel()

        await asyncio.gather(
            *(stop_connection(connection) for connection in self.server_state.connections),
            *(stop_task(task) for task in self.server_state.tasks),
            return_exceptions=True
        )

        if hasattr(self, "servers"):
            await super().shutdown(sockets)
