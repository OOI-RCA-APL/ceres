import asyncio
import socket
import traceback
from asyncio import CancelledError, Task, gather
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
from typing_extensions import override
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn
from websockets.exceptions import ConnectionClosed

from ceres.address import AbsoluteAddress, AddressSelector
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
from ceres.internal.context import ProjectContext
from ceres.internal.tasklet import Tasklet
from ceres.internal.utilities import sleep_forever, strify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.procedure import ProcedureBinding
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from uvicorn.server import Protocols

    from ceres.engine import Engine
else:
    Engine = "Engine"
    Protocols = "Protocols"


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
    started: Sequence[AbsoluteAddress]


@api.post("/start", tags=["engine"])
async def start(engine: CurrentEngine, query: ComponentQuery) -> StartResult:
    stopped = engine.get_components(query, running=False)
    stopped.start()
    return StartResult(started=[component.address for component in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[AbsoluteAddress]


@api.post("/stop", tags=["engine"])
async def stop(engine: CurrentEngine, query: ComponentQuery) -> StopResult:
    running = engine.get_components(query, running=True)
    await running.stop()
    return StopResult(stopped=[component.address for component in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[AbsoluteAddress]


@api.post("/enable", tags=["engine"])
async def enable(engine: CurrentEngine, query: ComponentQuery) -> EnableResult:
    disabled = engine.get_components(query, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[component.address for component in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[AbsoluteAddress]


@api.post("/disable", tags=["engine"])
async def disable(engine: CurrentEngine, query: ComponentQuery) -> DisableResult:
    enabled = engine.get_components(query, enabled=True)
    await enabled.enable()
    return DisableResult(disabled=[component.address for component in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[AbsoluteAddress]
    started: Sequence[AbsoluteAddress]


@api.post("/up", tags=["engine"])
async def up(engine: CurrentEngine, query: ComponentQuery) -> UpResult:
    disabled = engine.get_components(query, enabled=False)
    await disabled.enable()

    stopped = engine.get_components(query, running=False)
    stopped.start()

    return UpResult(
        enabled=[component.address for component in disabled],
        started=[component.address for component in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[AbsoluteAddress]
    stopped: Sequence[AbsoluteAddress]


@api.post("/down", tags=["engine"])
async def down(engine: CurrentEngine, query: ComponentQuery) -> DownResult:
    enabled = engine.get_components(query, enabled=True)
    await enabled.disable()

    running = engine.get_components(query, running=True)
    await running.stop()

    return DownResult(
        disabled=[component.address for component in enabled],
        stopped=[component.address for component in running],
    )


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
    address: AddressSelector | None = None,
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
    address: AddressSelector | None = None,
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
    address: AddressSelector | None = None,
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
            from ceres.internal.server import App

            app = scope.get("app")
            if not isinstance(app, App):
                return await send(message)

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


@final
class App(FastAPI):
    def __init__(self, engine: Engine) -> None:
        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
            middleware=[Middleware(HTTPLoggingMiddleware)],
        )

        self.__engine = engine
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

    @property
    def engine(self) -> Engine:
        return self.__engine


@final
class Server(Tasklet):
    def __init__(self, engine: Engine, config: Config) -> None:
        self.__engine = engine
        self.__config = config
        self.__app = App(engine)
        self.__port_uvicorn: _Uvicorn | None = None
        self.__uds_uvicorn: _Uvicorn | None = None

    @property
    def engine(self) -> Engine:
        return self.__engine

    @property
    def config(self) -> Config:
        return self.__config

    @override
    async def __run__(self) -> None:
        context = ProjectContext(self.__config)
        self.engine.local_directory.create()

        self.__uds_uvicorn = _Uvicorn(
            UvicornConfig(
                app=self.__app,
                uds=str(context.socket),
                loop="none",
            )
        )

        if self.__config.server.port is not None:
            self.__port_uvicorn = _Uvicorn(
                UvicornConfig(
                    app=self.__app,
                    port=self.__config.server.port,
                    loop="none",
                )
            )

        await gather(
            self.__uds_uvicorn.serve(),
            self.__port_uvicorn.serve() if self.__port_uvicorn is not None else sleep_forever(),
        )

    @override
    async def __stop__(self) -> None:
        if self.__port_uvicorn is not None:
            await self.__port_uvicorn.shutdown()
            self.__port_uvicorn = None
        if self.__uds_uvicorn is not None:
            await self.__uds_uvicorn.shutdown()
            self.__uds_uvicorn = None


class _Uvicorn(BaseUvicorn):
    @override
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        try:
            await super().serve(sockets)
        except SystemExit:
            # TODO: This occurs when the server's port couldn't be opened. We should probably try to
            # reconnect when this happens. For now, Uvicorn logs the error which should help
            # diagnose the problem.
            pass

    @override
    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass

    @override
    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        async def stop_connection(connection: Protocols) -> None:
            try:
                await connection.close()  # type: ignore
            except Exception:
                connection.shutdown()

        async def stop_task(task: Task[Any]) -> None:
            task.cancel()

        await asyncio.gather(
            *(stop_connection(connection) for connection in self.server_state.connections),
            *(stop_task(task) for task in self.server_state.tasks),
            return_exceptions=True,
        )

        if hasattr(self, "servers"):
            await super().shutdown(sockets)
