import asyncio
import json
import traceback
from asyncio import CancelledError
from dataclasses import dataclass
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
from ceres.component import Component, ProcedureBinding, Status
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
from ceres.internal.utilities import StrEnum, get_type_adapter, strify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.object import Statistics
from ceres.result import Fail, Ok, Result

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = object


class ComponentRole(StrEnum):
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


ComponentInfo.model_rebuild()

api = APIRouter()


def _get_current_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


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


def _get_procedure_query_args(
    query_args: Annotated[Json[Any], Query(alias="args")] = None,
) -> Mapping[str, object]:
    adapter = get_type_adapter(Mapping[str, object])

    try:
        if query_args is None:
            return {}
        if isinstance(query_args, str):
            return adapter.validate_json(query_args)
        return adapter.validate_python(query_args)
    except Exception:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'args' query parameter must be unspecified, null or a valid JSON object",
        )


CurrentProcedureQueryArgs = Annotated[Mapping[str, object], Depends(_get_procedure_query_args)]


@api.get("/config", tags=["engine"])
async def get_config(engine: CurrentEngine) -> Config:
    return engine.config


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


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@api.post("/start", tags=["components"])
async def start(engine: CurrentEngine, filter: ComponentFilter) -> StartResult:
    stopped = engine.get_components(filter, running=False)
    stopped.start()
    return StartResult(started=[component.address for component in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@api.post("/stop", tags=["components"])
async def stop(engine: CurrentEngine, filter: ComponentFilter) -> StopResult:
    running = engine.get_components(filter, running=True)
    await running.stop()
    return StopResult(stopped=[component.address for component in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@api.post("/enable", tags=["components"])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[component.address for component in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@api.post("/disable", tags=["components"])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()
    return DisableResult(disabled=[component.address for component in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@api.post("/up", tags=["components"])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()

    stopped = engine.get_components(filter, running=False)
    stopped.start()

    return UpResult(
        enabled=[component.address for component in disabled],
        started=[component.address for component in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@api.post("/down", tags=["components"])
async def down(engine: CurrentEngine, filter: ComponentFilter) -> DownResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()

    running = engine.get_components(filter, running=True)
    await running.stop()

    return DownResult(
        disabled=[component.address for component in enabled],
        stopped=[component.address for component in running],
    )


@api.get("/components/{address}", tags=["components"])
async def get_component(engine: CurrentEngine, address: Address) -> ComponentInfo:
    component_config = engine.config.get_component(address)
    if component_config is not None and type(component_config) is not ComponentConfig:
        component_config = ComponentConfig.model_validate(
            {
                "name": component_config.name,
                "class": component_config.cls_path,
                "args": component_config.args,
                "components": component_config.components,
            }
        )

    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    children: list[ComponentInfo] = []
    for child_config in component_config.components:
        children.append(await get_component(engine, address / child_config.name))

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
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    status = await engine.get_status(address)
    if status is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return status


class GetStatusesQueryParameters(ComponentFilter):
    pass


@api.get("/statuses", tags=["status"])
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[GetStatusesQueryParameters, Depends()],
) -> list[Status]:
    return await engine.get_statuses(filter)


class StreamStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@api.websocket("/statuses")
async def stream_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamStatusesQueryParameters, Depends()],
) -> None:
    async for statuses in engine.stream_statuses(filter):
        await socket.send(statuses)


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/messages", tags=["messages"])
async def get_messages(
    engine: CurrentEngine,
    filter: Annotated[GetMessagesQueryParameters, Depends()],
) -> list[Message]:
    return await engine.get_messages(filter)


class StreamMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@api.websocket("/messages")
async def stream_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamMessagesQueryParameters, Depends()],
) -> None:
    async for message in engine.stream_messages(filter):
        await socket.send(message)


class GetAlertsQueryParameters(AlertFilter):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/alerts", tags=["alerts"])
async def get_alerts(
    engine: CurrentEngine,
    filter: Annotated[GetAlertsQueryParameters, Depends()],
) -> list[Alert]:
    return await engine.get_alerts(filter)


class StreamAlertsQueryParameters(GetAlertsQueryParameters):
    pass


@api.websocket("/alerts")
async def stream_alerts(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamAlertsQueryParameters, Depends()],
) -> None:
    async for alert in engine.stream_alerts(filter):
        await socket.send(alert)


class GetLogEntriesQueryParameters(LogEntryFilter):
    level: Level | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/log-entries", tags=["logs"])
async def get_log_entries(
    engine: CurrentEngine,
    filter: Annotated[GetLogEntriesQueryParameters, Depends()],
) -> list[LogEntry]:
    return await engine.get_log_entries(filter)


class StreamLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@api.websocket("/log-entries")
async def stream_log_entries(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamLogEntriesQueryParameters, Depends()],
) -> None:
    async for entry in engine.stream_log_entries(filter):
        await socket.send(entry)


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[GetStatisticsQueryParameters, Depends()],
) -> list[Statistics]:
    return await engine.get_statistics(filter)


@api.api_route(
    "/components/{address}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
    query_args: CurrentProcedureQueryArgs,
    body_args: Mapping[Name, object] | None = Body(None),
) -> Result[Any | None, ProcedureError]:
    if isinstance(query_args, str):
        try:
            query_args = json.loads(query_args)
        except Exception:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "'args' query parameter must be unspecified, null or a valid JSON object",
            )

    if not isinstance(query_args, Mapping | None):
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'args' query parameter must be unspecified, null or a valid JSON object",
        )

    args = {}
    args.update(query_args or {})
    args.update(body_args or {})
    args.update(request.query_params)
    args.pop("args", None)

    try:
        component = engine.root.get_component(address)
        if component is None:
            return Fail(ProcedureComponentDoesNotExistError())
        return Ok(await component.call(procedure, args))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/components/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
    query_args: CurrentProcedureQueryArgs,
) -> None:
    await socket.accept()

    args = {}
    args.update(query_args or {})
    args.update(socket.query_params)
    args.pop("args", None)

    component = engine.root.get_component(address)
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
        )

        self.__engine = engine

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
        self.add_middleware(LoggingMiddleware)
        self.add_middleware(GZipMiddleware)

        @self.on_event("startup")
        def startup() -> None:
            logs.setup()

        self.include_router(api, prefix="/api")
        self.mount("/", ConsoleFiles(), name="console")

    @property
    def engine(self) -> Engine:
        return self.__engine
