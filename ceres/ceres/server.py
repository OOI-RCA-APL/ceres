from typing import Any

from fastapi import FastAPI, Response
from starlette.status import HTTP_200_OK, HTTP_406_NOT_ACCEPTABLE
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from . import logs
from .config import ServerConfig
from .engine import Engine


class Server(UvicornServer):  # type: ignore
    def __init__(self, config: ServerConfig, app: Engine):
        super().__init__(
            UvicornConfig(
                app=self.create_app(app),
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
    def create_app(cls, engine: Engine) -> FastAPI:
        app = FastAPI()

        @app.post("/reload")
        async def reload() -> Response:
            error = await engine.reload()
            return Response(status_code=HTTP_406_NOT_ACCEPTABLE if error else HTTP_200_OK)

        return app
