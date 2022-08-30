from __future__ import annotations

from typing import Any, Generic, Literal, Protocol, TypeVar, cast

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic.generics import GenericModel
from starlette.status import HTTP_400_BAD_REQUEST
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from ..config import EngineConfig, ServerConfig
from ..loader import EngineConfigError
from ..result import Fail, Ok, Result
from . import logs
from .tasks import Tasklet


class ServerEngineProtocol(Protocol):
    @property
    def config(self) -> EngineConfig:
        ...

    async def reload(self) -> Result[EngineConfig, list[EngineConfigError]]:
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

        @app.post(
            "/reload",
            response_model=cast(Any, Success[EngineConfig] | Error[list[EngineConfigError]]),
        )
        async def reload() -> Any:
            match await engine.reload():
                case Ok(config):
                    return Success.create(config)
                case Fail(errors):
                    return Error.response(errors, HTTP_400_BAD_REQUEST)

        return app


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

    @classmethod
    def response(cls, data: SuccessDataT, status: int) -> JSONResponse:
        return JSONResponse(cls.create(data).dict(), status)


class Error(GenericModel, Generic[ErrorDataT]):
    status: Literal["error"] = "error"
    data: ErrorDataT

    @classmethod
    def create(cls, data: ErrorDataT) -> Error[ErrorDataT]:
        return Error(data=data)

    @classmethod
    def response(cls, data: ErrorDataT, status: int) -> JSONResponse:
        return JSONResponse(cls.create(data).dict(), status)
