import traceback
from contextlib import asynccontextmanager
from http.client import responses
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, cast, final

from asgiref.typing import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    ASGISendEvent,
    HTTPScope,
    Scope,
    WebSocketScope,
)
from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from ceres.alert import Level
from ceres.internal import logs

from ceres.internal.app.api import router as router__api
from ceres.internal.app.console import ConsoleFiles
from ceres.internal.app.shared import CurrentEngine

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = object


router = APIRouter()


@router.get("/favicon.ico")
def get_favicon_ico(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".ico", "image/x-icon")


@router.get("/favicon.png")
def get_favicon_png(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".png", "image/png")


@router.get("/favicon.svg")
def get_favicon_svg(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".svg", "image/svg+xml")


@final
class App(FastAPI):
    def __init__(self, engine: Engine, *, cli: bool = False, **kwargs: Any) -> None:
        self.__engine = engine
        self.__cli = cli

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            logs.setup()
            yield

        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
            lifespan=lifespan,
        )

        @self.middleware("http")
        async def error_middleware(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            try:
                return await call_next(request)
            except Exception:
                self.engine.log.error(traceback.format_exc())
                raise

        self.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.add_middleware(LoggingMiddleware)  # type: ignore
        self.add_middleware(GZipMiddleware)

        self.include_router(router__api)
        self.include_router(router)
        self.mount("/", ConsoleFiles(), name="console")

    @property
    def engine(self) -> Engine:
        return self.__engine

    @property
    def cli(self) -> bool:
        return self.__cli


class LoggingMiddleware:
    def __init__(self, app: "App") -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        async def receive_wrapper() -> ASGIReceiveEvent:
            return await receive()

        async def send_wrapper(message: ASGISendEvent) -> None:
            from ceres.internal.app.main import App

            app = scope.get("app")

            if isinstance(app, App):
                try:
                    if message["type"] == "http.response.start" and scope["type"] == "http":
                        http = cast(HTTPScope, scope)  # type: ignore
                        path = http["path"]
                        verb = http["method"]
                        client = http["client"]
                        host = client[0] if client else "?"

                        status = message["status"]
                        description = responses.get(status, "Unknown")
                        level = Level.INFO if status < 400 else Level.ERROR

                        app.engine.log.write(
                            level,
                            f"[HTTP] {verb} {path} {host} {status} {description}",
                        )
                    elif (
                        message["type"] == "websocket.accept"
                        or message["type"] == "websocket.close"
                        and scope["type"] == "websocket"
                    ):
                        socket = cast(WebSocketScope, scope)  # type: ignore
                        type = message["type"]
                        path = socket["path"]
                        match type:
                            case "websocket.accept":
                                verb = "ACCEPT"
                            case "websocket.close":
                                verb = "CLOSE"
                        client = socket["client"]
                        host = client[0] if client else "?"

                        app.engine.log.info(f"[WS] '{verb}' {path} {host}")
                except Exception:
                    traceback.print_exc()

            return await send(message)

        return await self.app(scope, receive_wrapper, send_wrapper)  # type: ignore


def _get_favicon_response(
    engine: CurrentEngine,
    suffix: str,
    media_type: str,
) -> FileResponse:
    if engine.config.console.favicon is None or engine.config.console.favicon.suffix != suffix:
        path = Path(__file__).parent / ("../../static/console/favicon" + suffix)
    else:
        path = engine.config.console.favicon

    return FileResponse(path, media_type=media_type)
