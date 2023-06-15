import asyncio
import traceback
from asyncio import CancelledError
from enum import Enum
from http.client import responses
from typing import TYPE_CHECKING, Annotated, Any, Mapping, Sequence, cast, final

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
from pydantic import Field, Json
from starlette.middleware import Middleware
from starlette.requests import HTTPConnection
from starlette.status import HTTP_400_BAD_REQUEST
from websockets.exceptions import ConnectionClosed

from ceres.address import AbsoluteAddress, Address, AddressPattern
from ceres.alert import Alert, Level
from ceres.component import (
    AlertQuery,
    Component,
    ComponentQuery,
    LogEntryQuery,
    MessageQuery,
    Statistics,
    StatisticsQuery,
)
from ceres.config import ComponentConfig, Config
from ceres.data import ImmutableDataObject, Name, jsonify
from ceres.errors import (
    ProcedureComponentDoesNotExistError,
    ProcedureError,
    ProcedureInternalError,
    ReloadError,
)
from ceres.events import (
    AlertEvent,
    LogEvent,
    MessageReceivedEvent,
    MessageSentEvent,
)
from ceres.exceptions import ProcedureException
from ceres.internal import logs
from ceres.internal.console import ConsoleFiles
from ceres.internal.utilities import strify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.procedure import ProcedureBinding
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = "Engine"


class ComponentRole(str, Enum):
    ALERTER = "alerter"
    CONNECTION = "connection"
    DISPATCHER = "dispatcher"
    NOTIFIER = "notifier"
    UI = "ui"


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ceres.roles.alerter import Alerter
    from ceres.roles.connection import Connection
    from ceres.roles.dispatcher import Dispatcher
    from ceres.roles.notifier import Notifier
    from ceres.roles.ui import UI

    roles: list[ComponentRole] = []
    if issubclass(component, Alerter):
        roles.append(ComponentRole.ALERTER)
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, Dispatcher):
        roles.append(ComponentRole.DISPATCHER)
    if issubclass(component, Notifier):
        roles.append(ComponentRole.NOTIFIER)
    if issubclass(component, UI):
        roles.append(ComponentRole.UI)

    return roles


class ComponentInfo(ImmutableDataObject):
    name: Name
    address: AbsoluteAddress
    components: Sequence["ComponentInfo"]
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


ComponentInfo.update_forward_refs()

api = APIRouter()


def _get_current_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


@api.get("/config", tags=["engine"])
async def get_config(engine: CurrentEngine) -> Config:
    return engine.config


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@api.post("/start", tags=["engine"])
async def start(
    engine: CurrentEngine,
    query: ComponentQuery,
) -> StartResult:
    components = engine.get_components(query)
    started = [component.address for component in components if not component.running]
    components.start()
    return StartResult(started=started)


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@api.post("/stop", tags=["engine"])
async def stop(
    engine: CurrentEngine,
    query: ComponentQuery,
) -> StopResult:
    components = engine.get_components(query)
    stopped = [component.address for component in components if component.running]
    await components.stop()
    return StopResult(stopped=stopped)


@api.post("/reload", tags=["engine"])
async def reload(
    engine: CurrentEngine,
    response: Response,
) -> Result[Config, ReloadError]:
    match await engine.reload():
        case Ok(config):
            return Ok(config)
        case Fail(error):
            response.status_code = HTTP_400_BAD_REQUEST
            return Fail(error)


class GetMessagesQueryParameters(MessageQuery):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/messages", tags=["data"])
async def get_messages(
    engine: CurrentEngine,
    query: Annotated[GetMessagesQueryParameters, Depends()],
) -> list[Message]:
    return await engine.get_messages(query)


class GetAlertsQueryParameters(AlertQuery):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/alerts", tags=["data"])
async def get_alerts(
    engine: CurrentEngine,
    query: Annotated[GetAlertsQueryParameters, Depends()],
) -> list[Alert]:
    return await engine.get_alerts(query)


class GetLogEntriesQueryParameters(LogEntryQuery):
    address: AbsoluteAddress | None = None
    level: Level | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/log-entries", tags=["data"])
async def get_log_entries(
    engine: CurrentEngine,
    query: Annotated[GetLogEntriesQueryParameters, Depends()],
) -> list[LogEntry]:
    return await engine.get_log_entries(query)


class GetStatisticsQueryParameters(StatisticsQuery):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    engine: CurrentEngine,
    query: Annotated[GetStatisticsQueryParameters, Depends()],
) -> list[Statistics]:
    return await engine.get_statistics(query)


@api.websocket("/message-stream")
async def message_stream(
    socket: WebSocket,
    engine: CurrentEngine,
    address: AddressPattern | None = None,
    search: str | None = None,
) -> None:
    try:
        await socket.accept()

        query = MessageQuery(address=address, search=search)
        async for event in engine.events.of(MessageSentEvent | MessageReceivedEvent):
            if query.matches(event.message, engine.address):
                await socket.send_text(jsonify(event.message))
    except (WebSocketDisconnect, ConnectionClosed):
        raise
        pass


@api.websocket("/alert-stream")
async def alert_stream(
    socket: WebSocket,
    engine: CurrentEngine,
    address: AbsoluteAddress | None = None,
    search: str | None = None,
) -> None:
    try:
        await socket.accept()

        query = AlertQuery(address=address, search=search)
        async for event in engine.events.of(AlertEvent):
            if query.matches(event.alert, engine.address):
                await socket.send_text(jsonify(event.alert))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.websocket("/log-entry-stream")
async def log_entry_stream(
    socket: WebSocket,
    engine: CurrentEngine,
    address: AbsoluteAddress | None = None,
    search: str | None = None,
) -> None:
    try:
        await socket.accept()

        query = LogEntryQuery(address=address, search=search)
        async for event in engine.events.of(LogEvent):
            if query.matches(event.entry, engine.address):
                await socket.send_text(jsonify(event.entry))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.get("/components/{address}", tags=["components"])
async def get_component_info(
    engine: CurrentEngine,
    address: AbsoluteAddress,
) -> ComponentInfo:
    component_config = engine.config.get_component(address)
    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(404)

    children: list[ComponentInfo] = []
    for child_config in component_config.components:
        children.append(await get_component_info(engine, address / child_config.name))

    return ComponentInfo(
        name=component_config.name,
        address=address,
        config=component_config,
        roles=_get_component_roles(component_cls),
        procedures=list(component_cls.get_procedure_bindings().values()),
        components=children,
    )


@api.api_route(
    "/components/{address}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    engine: CurrentEngine,
    address: AbsoluteAddress,
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
        component = engine.get_component(address)
        if component is None:
            return Fail(ProcedureComponentDoesNotExistError())
        return Ok(await component.call(procedure, args))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/components/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
    address: AbsoluteAddress,
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

    component = engine.get_component(address)
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


class HTTPLoggingMiddleware:
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
            if not isinstance(app, App):
                return await send(message)

            try:
                if message["type"] == "http.response.start" and scope["type"] == "http":
                    http = cast(HTTPScope, scope)
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
                    socket = cast(WebSocketScope, scope)
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


@final
class App(FastAPI):
    def __init__(self, engine: Engine) -> None:
        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
            middleware=[Middleware(HTTPLoggingMiddleware)],
        )

        self.engine = engine
        self.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        @self.on_event("startup")
        def startup() -> None:
            logs.setup()

        self.include_router(api, prefix="/api")
        self.mount("/", ConsoleFiles(), name="console")
