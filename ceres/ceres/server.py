from typing import Any, Optional, Protocol

from fastapi import FastAPI, Response
from starlette.status import HTTP_200_OK, HTTP_406_NOT_ACCEPTABLE
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from . import logs
from .config import ServerConfig
from .exceptions import ConfigException


class ServerEngineProtocol(Protocol):
    async def reload(self) -> Optional[ConfigException]:
        ...


class Server(UvicornServer):  # type: ignore
    def __init__(
        self,
        config: ServerConfig,
        engine: ServerEngineProtocol,
    ):
        super().__init__(
            UvicornConfig(
                app=self.create_app(engine),
                port=config.port,
                loop="none",
            )
        )

    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)
        logs.setup()

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass

    async def stop(self) -> None:
        if hasattr(self, "servers"):
            await self.shutdown()

    @classmethod
    def create_app(cls, engine: ServerEngineProtocol) -> FastAPI:
        app = FastAPI()

        @app.post("/reload")
        async def reload() -> Response:
            error = await engine.reload()
            return Response(status_code=HTTP_406_NOT_ACCEPTABLE if error else HTTP_200_OK)

        return app
