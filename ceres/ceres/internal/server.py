from typing import Any, final

from starlette.types import ASGIApp
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn

from ..config import ServerConfig
from . import logs
from .tasklet import Tasklet


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
