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
        self._app = app
        self._config = config
        self._uvicorn: Uvicorn | None = None

    @property
    def app(self) -> ASGIApp:
        return self._app

    @property
    def config(self) -> ServerConfig:
        return self._config

    async def __run__(self) -> None:
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=self.app,
                port=self.config.port,
                loop="none",
            )
        )

        await self._uvicorn.serve()

    async def __stop__(self) -> None:
        if self._uvicorn is not None:
            await self._uvicorn.shutdown()
            self._uvicorn = None


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
