from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypeVar, cast

from fastapi import FastAPI, Response
from pydantic.generics import GenericModel
from starlette.status import HTTP_400_BAD_REQUEST
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from ..config import Config, ServerConfig
from ..errors import ReloadError
from ..result import Fail, Ok, Result
from . import logs
from .tasks import Tasklet
from .utilities import unreachable


class ServerEngineProtocol(Protocol):
    @property
    def config(self) -> Config:
        ...

    async def reload(self) -> Result[Config, ReloadError]:
        ...


class Server(Tasklet):
    def __init__(
        self,
        config: ServerConfig,
        engine: ServerEngineProtocol,
    ):
        self._config = config
        self._engine = engine
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=create_app(engine),
                port=config.port,
                loop="none",
            )
        )

    async def _tasklet_run(self) -> None:
        await self._uvicorn.serve()

    async def _tasklet_stop(self) -> None:
        if hasattr(self._uvicorn, "servers"):
            await self._uvicorn.shutdown()


class Uvicorn(UvicornServer):  # type: ignore
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass


SuccessDataT = TypeVar("SuccessDataT")
ErrorDataT = TypeVar("ErrorDataT")


class Success(GenericModel, Generic[SuccessDataT]):
    status: Literal["ok"] = "ok"
    data: SuccessDataT

    @classmethod
    def create(cls, data: SuccessDataT) -> Success[SuccessDataT]:
        return Success(data=data)


class Error(GenericModel, Generic[ErrorDataT]):
    status: Literal["error"] = "error"
    data: ErrorDataT

    @classmethod
    def create(cls, data: ErrorDataT) -> Error[ErrorDataT]:
        return Error(data=data)


def create_app(engine: ServerEngineProtocol) -> FastAPI:
    app = FastAPI()

    @app.on_event("startup")
    def startup() -> None:
        logs.setup()

    @app.get("/config", response_model=Config)
    async def config() -> Config:
        return engine.config

    @app.post(
        "/reload",
        response_model=cast(Any, Success[Config] | Error[ReloadError]),
    )
    async def reload(response: Response) -> Success[Config] | Error[ReloadError]:
        match await engine.reload():
            case Ok(config):
                return Success.create(config)
            case Fail(error):
                response.status_code = HTTP_400_BAD_REQUEST
                return Error.create(error)

        unreachable()

    return app
