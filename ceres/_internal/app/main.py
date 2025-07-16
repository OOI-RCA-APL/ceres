from __future__ import annotations

import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast, final

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException
from starlette.status import HTTP_422_UNPROCESSABLE_ENTITY

from ceres._internal import util
from ceres._internal.app.shared import CurrentEngine
from ceres.data import simplify
from ceres.error import (
    Failure,
    HTTPError,
    NotAuthenticatedError,
    ValidationFailedError,
    ValidationProblem,
)
from ceres.timing import utc
from ceres.version import __version__

if TYPE_CHECKING:
    from datetime import datetime

    from asgiref.typing import (
        ASGI3Application,
        ASGIReceiveCallable,
        ASGIReceiveEvent,
        ASGISendCallable,
        ASGISendEvent,
        Scope,
    )
    from fastapi.requests import HTTPConnection

    from ceres.config import ServerConfig
    from ceres.engine import Engine


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

        # Middlewares are run in reverse order. IE, this `CLIAuthMiddleware` is the last to be
        # entered on the way down the middleware stack.
        if self.__cli_token is not None:
            self.add_middleware(
                CLIAuthMiddleware,  # type: ignore
                self.__cli_token,
            )

        self.add_middleware(
            ScopeModifyMiddleware,  # type: ignore
        )
        self.add_middleware(
            ErrorMiddleware,  # type: ignore
            self.engine,
        )
        self.add_middleware(
            LoggingMiddleware,  # type: ignore
            self.engine,
        )

        from ceres.config import ServerCompressionConfig

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

        self.exception_handler(HTTPException)(self.__http_exception_handler)
        self.exception_handler(RequestValidationError)(self.__request_validation_error_handler)

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

    @property
    def cli_token(self) -> str | None:
        return self.__cli_token

    async def __http_exception_handler(
        self,
        request: HTTPConnection,
        exception: HTTPException,
    ) -> Response:
        error = simplify(HTTPError(status=exception.status_code))
        return JSONResponse(simplify(error), exception.status_code)

    async def __request_validation_error_handler(
        self,
        request: Request,
        exception: RequestValidationError,
    ) -> Response:
        error = simplify(ValidationFailedError(problems=ValidationProblem.extract(exception)))
        return JSONResponse(simplify(error), HTTP_422_UNPROCESSABLE_ENTITY)


class LoggingMiddleware:
    def __init__(self, app: ASGI3Application, engine: Engine) -> None:
        self.app = app
        self.engine = engine

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        from http.client import responses

        connected_at: datetime | None = None

        def duration() -> str:
            if connected_at is None:
                return ""

            duration = util.encode_td(utc() - connected_at, decimals=2, space=True)
            return f" ({duration})" if connected_at is not None else ""

        def handle(event: ASGIReceiveEvent | ASGISendEvent) -> None:
            nonlocal connected_at

            match scope["type"]:
                case "http":
                    if event["type"] == "http.request" or event["type"] == "http.response.start":
                        path = scope["path"]
                        verb = scope["method"].upper()
                        client = scope["client"]
                        host = client[0] if client else "?"

                        if event["type"] == "http.request":
                            connected_at = utc()
                            self.engine.log.debug(f"[HTTP] {verb} {path} {host}")
                        else:
                            status = event["status"]
                            description = responses.get(status, "Unknown")
                            self.engine.log.debug(
                                f"[HTTP] {verb} {path} {host} {status} {description}{duration()}"
                            )
                case "websocket":
                    if (
                        event["type"] == "websocket.connect"
                        or event["type"] == "websocket.accept"
                        or event["type"] == "websocket.close"
                        or event["type"] == "websocket.disconnect"
                    ):
                        path = scope["path"]
                        verb = event["type"].split(".")[1].upper()
                        client = scope["client"]
                        host = client[0] if client else "?"

                        if event["type"] == "websocket.connect":
                            connected_at = utc()
                            self.engine.log.debug(f"[WS] {verb} {path} {host}")
                        elif (
                            event["type"] == "websocket.close"
                            or event["type"] == "websocket.disconnect"
                        ):
                            code = event["code"]
                            self.engine.log.debug(f"[WS] {verb} {path} {host} {code}{duration()}")
                        else:
                            self.engine.log.debug(f"[WS] {verb} {path} {host}{duration()}")
                case "lifespan":
                    pass

        async def receive_wrapper() -> ASGIReceiveEvent:
            event = await receive()
            handle(event)
            return event

        async def send_wrapper(event: ASGISendEvent) -> None:
            handle(event)
            await send(event)

        await self.app(scope, receive_wrapper, send_wrapper)


class ScopeModifyMiddleware:
    def __init__(self, app: ASGI3Application) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        # Remove the "http.response.pathsend" extension from the scope as it conflicts with
        # `CompressMiddleware` at the time of writing.
        extensions = scope.get("extensions")
        if extensions is not None:
            extensions.pop("http.response.pathsend", None)

        # Combine multiple cookie headers into a single header. Starlette doesn't support multiple
        # cookie headers, despite them being the sent by default on HTTP/2 and above in Chrome.
        headers = scope.get("headers", [])
        if not isinstance(headers, list):
            headers = list(headers)

        cookie_header_index: int | None = None
        cookie_header_values: list[bytes] = []

        for i, (key, value) in enumerate(headers):
            if key.lower() == b"cookie":
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

        return await self.app(scope, receive, send)


class CLIAuthMiddleware:
    def __init__(self, app: ASGI3Application, cli_token: str) -> None:
        self.app = app
        self.cli_token = cli_token

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)

        request = Request(cast("Any", scope))
        if request.headers.get("Authorization") != self.cli_token:
            raise Failure(NotAuthenticatedError)

        return await self.app(scope, receive, send)


class ErrorMiddleware:
    def __init__(self, app: ASGI3Application, engine: Engine) -> None:
        self.app = app
        self.engine = engine

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        try:
            await self.app(scope, receive, send)
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
                await JSONResponse(error, status)(
                    scope,  # type: ignore
                    receive,  # type: ignore
                    send,  # type: ignore
                )
            except Exception:
                self.engine.log.error(traceback.format_exc())
                raise
        except Exception:
            self.engine.log.error(traceback.format_exc())
            raise


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
