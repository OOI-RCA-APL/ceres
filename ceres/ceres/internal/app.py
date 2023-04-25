import asyncio
from asyncio import CancelledError
from enum import Enum
from typing import TYPE_CHECKING, Annotated, Any, Mapping, Sequence, final

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
from starlette.requests import HTTPConnection
from starlette.status import HTTP_400_BAD_REQUEST
from websockets.exceptions import ConnectionClosed

from ceres.address import Address
from ceres.alert import Alert, AlertLevel
from ceres.component import Component
from ceres.config import ComponentConfig, Config, UnitConfig
from ceres.data import ImmutableDataObject, Name, jsonify
from ceres.environment import (
    AlertQuery,
    Environment,
    MessageQuery,
    Statistics,
    StatisticsQuery,
)
from ceres.errors import ProcedureError, ProcedureInternalError, ReloadError
from ceres.events import AlertEmittedEvent, MessageReceivedEvent, MessageSentEvent
from ceres.exceptions import ProcedureException
from ceres.internal import logs
from ceres.internal.console import ConsoleFiles
from ceres.internal.utilities import strify
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
    address: Address
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


class UnitInfo(ImmutableDataObject):
    name: str
    config: UnitConfig
    components: Sequence[ComponentInfo]


api = APIRouter()


def _get_current_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


def _get_current_environment(connection: HTTPConnection) -> Environment:
    return _get_current_engine(connection).environment


CurrentEnvironment = Annotated[Environment, Depends(_get_current_environment)]


@api.get("/config", tags=["engine"])
async def get_config(engine: CurrentEngine) -> Config:
    return engine.config


@api.post("/reload", tags=["engine"])
async def reload(
    response: Response,
    engine: CurrentEngine,
) -> Result[Config, ReloadError]:
    match await engine.reload():
        case Ok(config):
            return Ok(config)
        case Fail(error):
            response.status_code = HTTP_400_BAD_REQUEST
            return Fail(error)


class GetMessagesQueryParameters(MessageQuery):
    source: Address | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/messages", tags=["data"])
async def get_messages(
    query: Annotated[GetMessagesQueryParameters, Depends()],
    environment: CurrentEnvironment,
) -> list[Message]:
    return await environment.get_messages(query)


class GetAlertsQueryParameters(AlertQuery):
    source: Address | None = None
    level: AlertLevel | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/alerts", tags=["data"])
async def get_alerts(
    environment: CurrentEnvironment,
    query: Annotated[GetAlertsQueryParameters, Depends()],
) -> list[Alert]:
    return await environment.get_alerts(query)


class GetStatisticsQueryParameters(StatisticsQuery):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    environment: CurrentEnvironment,
    query: Annotated[GetStatisticsQueryParameters, Depends()],
) -> Statistics:
    return await environment.get_statistics(query)


@api.websocket("/message-stream")
async def message_stream(
    socket: WebSocket,
    engine: CurrentEngine,
    source: Address | None = None,
    search: str | None = None,
) -> None:
    try:
        await socket.accept()

        query = MessageQuery(source=source, search=search)
        async for event in engine.events.of(MessageSentEvent | MessageReceivedEvent):
            if query.matches(event.message):
                await socket.send_text(jsonify(event.message))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.websocket("/alert-stream")
async def alert_stream(
    socket: WebSocket,
    engine: CurrentEngine,
    source: Address | None = None,
    search: str | None = None,
) -> None:
    try:
        await socket.accept()

        query = AlertQuery(source=source, search=search)
        async for event in engine.events.of(AlertEmittedEvent):
            if query.matches(event.alert):
                await socket.send_text(jsonify(event))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.get("/units/{unit}", tags=["units"])
async def get_unit_info(
    engine: CurrentEngine,
    unit: Name,
) -> UnitInfo:
    config = engine.config.get_unit(unit)
    if config is None:
        raise HTTPException(404)

    components = []
    for component in config.components:
        components.append(
            await get_component_info(
                engine,
                unit,
                component.name,
            )
        )

    return UnitInfo(
        name=config.name,
        config=config,
        components=components,
    )


@api.get("/units/{unit}/components/{component}", tags=["components"])
async def get_component_info(
    engine: CurrentEngine,
    unit: Name,
    component: Name,
) -> ComponentInfo:
    address = Address.create(unit, component)
    component_config = engine.config.get_component(address)
    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(404)

    return ComponentInfo(
        name=component,
        address=address,
        config=component_config,
        roles=_get_component_roles(component_cls),
        procedures=list(component_cls.get_procedure_bindings().values()),
    )


@api.api_route(
    "/units/{unit}/components/{component}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    engine: CurrentEngine,
    unit: Name,
    component: Name,
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
        return Ok(await engine.call(Address.create(unit, component), procedure, args))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/units/{unit}/components/{component}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
    unit: Name,
    component: Name,
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

    address = Address.create(unit, component)

    args = {}
    args.update(query_args or {})
    args.update(socket.query_params)
    args.pop("args", None)

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
            async for output in engine.subscribe(address, procedure, args):
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


@final
class App(FastAPI):
    def __init__(self, engine: Engine) -> None:
        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
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
