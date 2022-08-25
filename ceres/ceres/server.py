from typing import Any, Generic, Literal, Optional, Protocol, Type, TypeVar, Union, cast

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.status import HTTP_400_BAD_REQUEST
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from . import logs
from .config import EngineConfig, ServerConfig
from .data import GenericDataObject
from .exceptions import ConfigException
from .tasks import Tasklet

OkDataT = TypeVar("OkDataT")
ErrorDataT = TypeVar("ErrorDataT")


class Ok(GenericDataObject, Generic[OkDataT]):
    status: Literal["ok"] = "ok"
    data: OkDataT

    @classmethod
    def create(cls, data: OkDataT) -> "Ok[OkDataT]":
        return Ok(data=data)

    @classmethod
    def response(cls, data: OkDataT, status: int) -> JSONResponse:
        return JSONResponse(cls.create(data), status)


class Error(GenericDataObject, Generic[ErrorDataT]):
    status: Literal["error"] = "error"
    data: ErrorDataT

    @classmethod
    def create(cls, data: ErrorDataT) -> "Error[ErrorDataT]":
        return Error(data=data)

    @classmethod
    def response(cls, data: ErrorDataT, status: int) -> JSONResponse:
        return JSONResponse(cls.create(data), status)


class ServerEngineProtocol(Protocol):
    @property
    def config(self) -> EngineConfig:
        ...

    async def reload(self) -> Optional[ConfigException]:
        ...


class InternalUvicornServer(UvicornServer):  # type: ignore
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass


class Server(Tasklet):
    def __init__(
        self,
        config: ServerConfig,
        engine: ServerEngineProtocol,
    ):
        self._config = config
        self._engine = engine
        self._uvicorn = InternalUvicornServer(
            UvicornConfig(
                app=self._create_app(engine),
                port=config.port,
                loop="none",
            )
        )

    async def _tasklet_run(self) -> None:
        await self._uvicorn.serve()

    async def _tasklet_stop(self) -> None:
        if hasattr(self._uvicorn, "servers"):
            await self._uvicorn.shutdown()

    @classmethod
    def _create_app(cls, engine: ServerEngineProtocol) -> FastAPI:
        app = FastAPI()

        @app.on_event("startup")
        def startup() -> None:
            logs.setup()

        @app.post("/reload", response_model=cast(Type[Any], Union[Ok[EngineConfig], Error[str]]))
        async def reload() -> Any:
            if error := await engine.reload():
                return Error.response(error.message, HTTP_400_BAD_REQUEST)

            return Ok.create(engine.config)

        return app
