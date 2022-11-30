from logging import Logger
from typing import TYPE_CHECKING, Any, final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn

from ..config import ServerConfig
from . import logs
from .console import Console
from .database.manager import DatabaseManager
from .tasklet import Tasklet

if TYPE_CHECKING:
    from ..engine import Engine
else:
    Engine = "Engine"


@final
class Server(Tasklet):
    def __init__(
        self,
        config: ServerConfig,
        engine: Engine,
    ):
        self._config = config
        self._engine = engine
        self._uvicorn: Uvicorn | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def database(self) -> DatabaseManager:
        return self._engine.database

    @property
    def logger(self) -> Logger:
        return logs.get("uvicorn")

    async def __run__(self) -> None:
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=self._generate_app(),
                port=self.config.port,
                loop="none",
            )
        )

        await self._uvicorn.serve()

    async def __stop__(self) -> None:
        if self._uvicorn is not None:
            await self._uvicorn.shutdown()
            self._uvicorn = None

    def _generate_app(self) -> FastAPI:
        app = FastAPI(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )
        app.state.engine = self.engine
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        from . import api

        app.include_router(api.router, prefix="/api")
        app.mount("/", Console(), name="console")
        return app


class Uvicorn(BaseUvicorn):
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass
