import traceback
from http.client import responses
from pathlib import Path
from typing import TYPE_CHECKING, Awaitable, Callable, cast, final

from asgiref.typing import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    ASGISendEvent,
    HTTPScope,
    Scope,
    WebSocketScope,
)
from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    WebSocketException,
)
from fastapi.dependencies.models import Dependant
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import AliasChoices
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY, WS_1008_POLICY_VIOLATION

from ceres._internal.app.api import router as router__api
from ceres._internal.app.console import ConsoleFiles
from ceres._internal.app.shared import CurrentEngine
from ceres.alert import Level
from ceres.data import jsonify, simplify
from ceres.error import Failure, HTTPError, ValidationFailedError
from ceres.validation import ValidationProblem
from ceres.version import __version__

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
    def __init__(self, engine: Engine) -> None:
        self.__engine = engine

        super().__init__(
            title="Ceres",
            version=__version__,
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
            dependencies=[Depends(_disallow_unknown_query_params)],
        )

        @self.middleware("http")
        async def error_middleware(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            try:
                return await call_next(request)
            except Failure as failure:
                try:
                    error = simplify(failure.error)
                    status = failure.error.__error_status_code__
                except Exception:
                    traceback.print_exc()
                    raise

                return JSONResponse(error, status)
            except Exception:
                self.engine.log.error(traceback.format_exc())
                raise

        @self.exception_handler(StarletteHTTPException)
        async def on_http_exception(
            request: Request,
            exception: HTTPException,
        ) -> Response:
            error = simplify(HTTPError(status=exception.status_code))
            return JSONResponse(simplify(error), status_code=exception.status_code)

        @self.exception_handler(RequestValidationError)
        async def on_request_validation_error(
            request: Request,
            exception: RequestValidationError,
        ) -> Response:
            error = simplify(ValidationFailedError(problems=ValidationProblem.extract(exception)))
            return JSONResponse(simplify(error), status_code=HTTP_422_UNPROCESSABLE_ENTITY)

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
            from ceres._internal.app.main import App

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

                        app.engine.log.emit(
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


def _disallow_unknown_query_params(connection: HTTPConnection) -> None:
    dependant = connection.scope["route"].dependant
    if not isinstance(dependant, Dependant):
        return

    allowed: set[str] = set()
    for dependency in [dependant, *dependant.dependencies]:
        for param in dependency.query_params:
            allowed.add(param.name)
            allowed.add(param.alias)
            field = param.field_info
            if field.validation_alias is not None:
                if isinstance(field.validation_alias, str):
                    allowed.add(field.validation_alias)
                if isinstance(field.validation_alias, AliasChoices):
                    for choice in field.validation_alias.choices:
                        if isinstance(choice, str):
                            allowed.add(choice)

    extra = set(connection.query_params.keys()).difference(allowed)
    if extra:
        error = ValidationFailedError(
            problems=[
                ValidationProblem(
                    type="extra_forbidden",
                    location=[param],
                    message="Extra inputs are not permitted",
                )
                for param in extra
            ]
        )

        if isinstance(connection, Request):
            raise Failure(
                ValidationFailedError(
                    problems=[
                        ValidationProblem(
                            type="extra_forbidden",
                            location=[param],
                            message="Extra inputs are not permitted",
                        )
                        for param in extra
                    ]
                )
            )

        raise WebSocketException(WS_1008_POLICY_VIOLATION, jsonify(error))
