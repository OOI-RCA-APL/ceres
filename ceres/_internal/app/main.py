from __future__ import annotations

import traceback
from http.client import responses
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, cast, final

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from ceres._internal import util
from ceres._internal.app.shared import CurrentEngine
from ceres._internal.lazy import lazy_imports
from ceres.error import (
    Failure,
    HTTPError,
    NotAuthenticatedError,
    ValidationFailedError,
    ValidationProblem,
)
from ceres.version import __version__

if TYPE_CHECKING:
    from asgiref.typing import (
        ASGIReceiveCallable,
        ASGIReceiveEvent,
        ASGISendCallable,
        ASGISendEvent,
        HTTPScope,
        Scope,
        WebSocketScope,
    )
    from fastapi.requests import HTTPConnection

    from ceres.engine import Engine

with lazy_imports(__name__):
    from ceres.config import ServerCompressionConfig, ServerConfig
    from ceres.data import simplify


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
    def __init__(
        self,
        engine: Engine,
        config: ServerConfig | None = None,
        cli_token: str | None = None,
    ) -> None:
        self.__cli_token = cli_token

        if config is None:
            config = engine.config.server

        self.__engine = engine

        super().__init__(
            title="Ceres",
            version=__version__,
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )

        compression = config.compression or ServerCompressionConfig()
        if compression.enabled:
            from starlette_compress import CompressMiddleware

            self.add_middleware(
                CompressMiddleware,
                minimum_size=int(compression.min_size),
                zstd=compression.zstd,
                zstd_level=compression.zstd_level,
                brotli=compression.brotli,
                brotli_quality=compression.brotli_quality,
                gzip=compression.gzip,
                gzip_level=compression.gzip_level,
            )

        from fastapi.middleware.cors import CORSMiddleware

        cors = config.cors
        if cors is not None and cors.enabled:
            self.add_middleware(
                CORSMiddleware,
                allow_origins=util.seq(cors.allow_origins),
                allow_methods=util.seq(cors.allow_methods),
                allow_headers=util.seq(cors.allow_headers),
                allow_credentials=cors.allow_credentials,
                allow_origin_regex=cors.allow_origin_regex.pattern
                if cors.allow_origin_regex
                else None,
                expose_headers=util.seq(cors.expose_headers),
                max_age=cors.max_age,
            )

        self.add_middleware(LoggingMiddleware)  # type: ignore

        self.middleware("http")(self._cli_token_middleware)
        self.middleware("http")(self._error_middleware)
        self.middleware("http")(self._scope_modify_middleware)
        self.exception_handler(HTTPException)(self._http_exception_handler)
        self.exception_handler(RequestValidationError)(self._request_validation_error_handler)

        from ceres._internal.app.api import router as api

        self.include_router(api)

        if not self.cli:
            from ceres._internal.app.console import ConsoleFiles

            self.include_router(router)
            self.mount("/", ConsoleFiles(), name="console")

    @property
    def engine(self) -> Engine:
        return self.__engine

    @property
    def cli(self) -> bool:
        return self.__cli_token is not None

    async def _cli_token_middleware(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if self.__cli_token is not None:
            if request.headers.get("Authorization") != self.__cli_token:
                raise Failure(NotAuthenticatedError)

        return await call_next(request)

    async def _error_middleware(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        try:
            return await call_next(request)
        except Failure as failure:
            try:
                error = simplify(failure.error)
                status = failure.error.__error_status_code__

                if status >= 500:
                    self.engine.log.error(traceback.format_exc())
            except Exception:
                traceback.print_exc()
                raise

            try:
                return JSONResponse(error, status)
            except Exception:
                self.engine.log.error(traceback.format_exc())
                raise
        except Exception:
            self.engine.log.error(traceback.format_exc())
            raise

    async def _scope_modify_middleware(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Remove the "http.response.pathsend" extension from the request scope as it causes issues
        # with FastAPI.
        extensions: dict[str, dict[str, Any]] | None = request.scope.get("extensions")
        if extensions is not None:
            extensions.pop("http.response.pathsend", None)

        # Combine multiple cookie headers into a single header. Starlette doesn't support multiple
        # cookie headers, despite them being the sent by default on HTTP/2 and above in Chrome.
        headers: list[tuple[bytes, bytes]] = request.scope.get("headers", [])
        cookie_header_index: int | None = None
        cookie_header_values: list[bytes] = []

        for i, (key, value) in enumerate(headers):
            if key == b"cookie":
                if cookie_header_index is None:
                    cookie_header_index = i

                cookie_header_values.append(value)

        if cookie_header_index is not None:
            merged_cookie_header = (b"cookie", b"; ".join(cookie_header_values))
            merged_headers = [
                (key, value)
                for i, (key, value) in enumerate(headers)
                if key != "cookie" or i == cookie_header_index
            ]
            merged_headers[cookie_header_index] = merged_cookie_header

            headers.clear()
            headers.extend(merged_headers)

        return await call_next(request)

    async def _http_exception_handler(
        self,
        request: HTTPConnection,
        exception: HTTPException,
    ) -> Response:
        error = simplify(HTTPError(status=exception.status_code))
        return JSONResponse(simplify(error), exception.status_code)

    async def _request_validation_error_handler(
        self,
        request: Request,
        exception: RequestValidationError,
    ) -> Response:
        error = simplify(ValidationFailedError(problems=ValidationProblem.extract(exception)))
        return JSONResponse(simplify(error), HTTP_422_UNPROCESSABLE_ENTITY)


class LoggingMiddleware:
    def __init__(self, app: App) -> None:
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
                        http = cast("HTTPScope", scope)
                        path = http["path"]
                        verb = http["method"]
                        client = http["client"]
                        host = client[0] if client else "?"

                        status = message["status"]
                        description = responses.get(status, "Unknown")

                        app.engine.log.debug(
                            f"[HTTP] {verb} {path} {host} {status} {description}",
                        )
                    elif (
                        message["type"] == "websocket.accept"
                        or message["type"] == "websocket.close"
                        and scope["type"] == "websocket"
                    ):
                        socket = cast("WebSocketScope", scope)
                        type = message["type"]
                        path = socket["path"]
                        match type:
                            case "websocket.accept":
                                verb = "ACCEPT"
                            case "websocket.close":
                                verb = "CLOSE"
                        client = socket["client"]
                        host = client[0] if client else "?"

                        app.engine.log.debug(f"[WS] {verb} {path} {host}")
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
