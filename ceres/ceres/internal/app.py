import asyncio
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
from enum import Enum
from http.client import responses
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Sequence,
    cast,
    final,
)

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
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from pydantic import Field, Json
from starlette.requests import HTTPConnection
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND
from websockets.exceptions import ConnectionClosed

from ceres.address import Address
from ceres.alert import Alert, Level
from ceres.component import Component, Status
from ceres.config import ComponentConfig, Config
from ceres.data import ImmutableDataObject, Name, jsonify
from ceres.errors import (
    ProcedureComponentDoesNotExistError,
    ProcedureError,
    ProcedureInternalError,
    ReloadError,
)
from ceres.exceptions import ProcedureException
from ceres.filter import (
    AlertFilter,
    ComponentFilter,
    LogEntryFilter,
    MessageFilter,
    StatisticsFilter,
)
from ceres.internal import logs
from ceres.internal.console import ConsoleFiles
from ceres.internal.utilities import strify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.object import Statistics
from ceres.procedure import ProcedureBinding
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres.server import Server
else:
    Server = object


class ComponentRole(str, Enum):
    CONNECTION = "connection"
    UI = "ui"


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ceres.roles.connection import Connection
    from ceres.roles.ui import UI

    roles: list[ComponentRole] = []
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, UI):
        roles.append(ComponentRole.UI)

    return roles


class ComponentInfo(ImmutableDataObject):
    name: Name
    address: Address
    components: Sequence["ComponentInfo"]
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


ComponentInfo.update_forward_refs()

api = APIRouter()


def _get_current_server(connection: HTTPConnection) -> Server:
    assert isinstance(connection.app, App)
    return connection.app.server


CurrentServer = Annotated[Server, Depends(_get_current_server)]


@dataclass
class Socket:
    socket: WebSocket

    async def send(self, data: Any) -> None:
        await self.socket.send_text(jsonify(data))

    async def receive(self) -> Any:
        await self.socket.receive_json()


async def _use_current_socket(socket: WebSocket) -> AsyncIterator[Socket]:
    try:
        await socket.accept()
        yield Socket(socket)
    except (WebSocketDisconnect, ConnectionClosed):
        pass


CurrentSocket = Annotated[Socket, Depends(_use_current_socket)]


@api.get("/config", tags=["server"])
async def get_config(server: CurrentServer) -> Config:
    return server.config


@api.post("/reload", tags=["server"])
async def reload(
    server: CurrentServer,
    response: Response,
) -> Result[Config, ReloadError]:
    match await server.reload():
        case Ok(config):
            return Ok(config)
        case Fail(error):
            response.status_code = HTTP_400_BAD_REQUEST
            return Fail(error)


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@api.post("/start", tags=["components"])
async def start(server: CurrentServer, filter: ComponentFilter) -> StartResult:
    stopped = server.get_components(filter, running=False)
    stopped.start()
    return StartResult(started=[component.address for component in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@api.post("/stop", tags=["components"])
async def stop(server: CurrentServer, filter: ComponentFilter) -> StopResult:
    running = server.get_components(filter, running=True)
    await running.stop()
    return StopResult(stopped=[component.address for component in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@api.post("/enable", tags=["components"])
async def enable(server: CurrentServer, filter: ComponentFilter) -> EnableResult:
    disabled = server.get_components(filter, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[component.address for component in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@api.post("/disable", tags=["components"])
async def disable(server: CurrentServer, filter: ComponentFilter) -> DisableResult:
    enabled = server.get_components(filter, enabled=True)
    await enabled.disable()
    return DisableResult(disabled=[component.address for component in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@api.post("/up", tags=["components"])
async def up(server: CurrentServer, filter: ComponentFilter) -> UpResult:
    disabled = server.get_components(filter, enabled=False)
    await disabled.enable()

    stopped = server.get_components(filter, running=False)
    stopped.start()

    return UpResult(
        enabled=[component.address for component in disabled],
        started=[component.address for component in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@api.post("/down", tags=["components"])
async def down(server: CurrentServer, filter: ComponentFilter) -> DownResult:
    enabled = server.get_components(filter, enabled=True)
    await enabled.disable()

    running = server.get_components(filter, running=True)
    await running.stop()

    return DownResult(
        disabled=[component.address for component in enabled],
        stopped=[component.address for component in running],
    )


@api.get("/components/{address}", tags=["components"])
async def get_component(server: CurrentServer, address: Address) -> ComponentInfo:
    component_config = server.config.get_component(address)
    if component_config is not None and type(component_config) is not ComponentConfig:
        component_config = ComponentConfig.parse_obj(
            {
                "name": component_config.name,
                "class": component_config.cls_path,
                "args": component_config.args,
                "components": component_config.components,
            }
        )

    component_cls = server.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    children: list[ComponentInfo] = []
    for child_config in component_config.components:
        children.append(await get_component(server, address / child_config.name))

    try:
        info = ComponentInfo(
            name=component_config.name,
            address=address,
            config=component_config,
            roles=_get_component_roles(component_cls),
            procedures=list(component_cls.get_procedure_bindings().values()),
            components=children,
        )
        return info
    except Exception:
        traceback.print_exc()
        raise


@api.get("/status/{address}?", tags=["status"])
async def get_status(server: CurrentServer, address: Address | None = None) -> Status:
    status = await server.get_status(address)
    if status is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return status


class GetStatusesQueryParameters(ComponentFilter):
    pass


@api.get("/statuses", tags=["status"])
async def get_statuses(
    server: CurrentServer,
    filter: Annotated[GetStatusesQueryParameters, Depends()],
) -> list[Status]:
    return await server.get_statuses(filter)


class StreamStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@api.websocket("/statuses")
async def stream_statuses(
    socket: CurrentSocket,
    server: CurrentServer,
    filter: Annotated[StreamStatusesQueryParameters, Depends()],
) -> None:
    async for statuses in server.stream_statuses(filter):
        await socket.send(statuses)


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/messages", tags=["messages"])
async def get_messages(
    server: CurrentServer,
    filter: Annotated[GetMessagesQueryParameters, Depends()],
) -> list[Message]:
    return await server.get_messages(filter)


class StreamMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@api.websocket("/messages")
async def stream_messages(
    socket: CurrentSocket,
    server: CurrentServer,
    filter: Annotated[StreamMessagesQueryParameters, Depends()],
) -> None:
    async for message in server.stream_messages(filter):
        await socket.send(message)


class GetAlertsQueryParameters(AlertFilter):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/alerts", tags=["alerts"])
async def get_alerts(
    server: CurrentServer,
    filter: Annotated[GetAlertsQueryParameters, Depends()],
) -> list[Alert]:
    return await server.get_alerts(filter)


class StreamAlertsQueryParameters(GetAlertsQueryParameters):
    pass


@api.websocket("/alerts")
async def stream_alerts(
    socket: CurrentSocket,
    server: CurrentServer,
    filter: Annotated[StreamAlertsQueryParameters, Depends()],
) -> None:
    async for alert in server.stream_alerts(filter):
        await socket.send(alert)


class GetLogEntriesQueryParameters(LogEntryFilter):
    level: Level | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/log-entries", tags=["logs"])
async def get_log_entries(
    server: CurrentServer,
    filter: Annotated[GetLogEntriesQueryParameters, Depends()],
) -> list[LogEntry]:
    return await server.get_log_entries(filter)


class StreamLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@api.websocket("/log-entries")
async def stream_log_entries(
    socket: CurrentSocket,
    server: CurrentServer,
    filter: Annotated[StreamLogEntriesQueryParameters, Depends()],
) -> None:
    async for entry in server.stream_log_entries(filter):
        await socket.send(entry)


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    server: CurrentServer,
    filter: Annotated[GetStatisticsQueryParameters, Depends()],
) -> list[Statistics]:
    return await server.get_statistics(filter)


@api.api_route(
    "/components/{address}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    server: CurrentServer,
    address: Address,
    procedure: Name,
    query_args: Json[Any] = Query(None, alias="args"),
    body_args: Mapping[Name, object] | None = Body(None),
) -> Result[Any | None, ProcedureError]:
    if not isinstance(query_args, Mapping | None):
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'input' query parameter must be unspecified, null or a valid JSON object",
        )

    args = {}
    args.update(query_args or {})
    args.update(body_args or {})
    args.update(request.query_params)
    args.pop("args", None)

    try:
        component = server.root.get_component(address)
        if component is None:
            return Fail(ProcedureComponentDoesNotExistError())
        return Ok(await component.call(procedure, args))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/components/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    server: CurrentServer,
    address: Address,
    procedure: Name,
    query_args: Json[Any] = Query(None, alias="args"),
) -> None:
    await socket.accept()
    if not isinstance(query_args, Mapping | None):
        await socket.close(
            code=1008,
            reason="'input' query parameter must be unspecified, null or a valid JSON object",
        )
        return

    args = {}
    args.update(query_args or {})
    args.update(socket.query_params)
    args.pop("args", None)

    component = server.root.get_component(address)
    if component is None:
        code = 1008  # Set code for policy violation.
        reason = jsonify(Fail(ProcedureComponentDoesNotExistError()))
        await socket.close(code, reason)
        return

    async def read() -> None:
        try:
            while True:
                await socket.receive_text()
        except Exception:
            pass
        finally:
            task_write.cancel()

    async def write() -> None:
        try:
            async for output in component.subscribe(procedure, args):
                await socket.send_text(jsonify(output))
        except Exception as exception:
            if isinstance(exception, ProcedureException):
                if not isinstance(exception.error, ProcedureInternalError):
                    code = 1011  # Set code for internal error.
                else:
                    code = 1008  # Set code for policy violation.

                reason = jsonify(Fail(exception.error))
            else:
                code = 1011  # Set code for internal error.
                reason = jsonify(strify(exception)[0:100])

            await socket.close(code, reason)
        finally:
            task_read.cancel()

    task_read = asyncio.create_task(read(), name="read")
    task_write = asyncio.create_task(write(), name="write")

    try:
        await asyncio.gather(task_read, task_write)
    except CancelledError:
        pass


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
            from ceres.internal.app import App

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

                        app.server.log.write(
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

                        app.server.log.info(f"[WS] '{verb}' {path} {host}")
                except Exception:
                    traceback.print_exc()

            return await send(message)

        return await self.app(scope, receive_wrapper, send_wrapper)  # type: ignore


@final
class App(FastAPI):
    def __init__(self, server: Server) -> None:
        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )

        self.__server = server

        @self.middleware("http")
        async def error_middleware(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            try:
                return await call_next(request)
            except Exception:
                self.server.log.error(traceback.format_exc())
                raise

        self.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.add_middleware(LoggingMiddleware)
        self.add_middleware(GZipMiddleware)

        @self.on_event("startup")
        def startup() -> None:
            logs.setup()

        self.include_router(api, prefix="/api")
        self.mount("/", ConsoleFiles(), name="console")

    @property
    def server(self) -> Server:
        return self.__server
