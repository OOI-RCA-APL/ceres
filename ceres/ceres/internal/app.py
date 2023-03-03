import asyncio
from asyncio import CancelledError
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Sequence, final

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    HTTPException,
    Query,
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
from ceres.layout import Layout
from ceres.message import Message
from ceres.procedure import ActionBinding, QueryBinding
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

    from ceres.connection import Connection
    from ceres.dispatcher import Dispatcher
    from ceres.notifier import Notifier

    roles: list[ComponentRole] = []
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, Dispatcher):
        roles.append(ComponentRole.DISPATCHER)
    if issubclass(component, Notifier):
        roles.append(ComponentRole.NOTIFIER)

    return roles


class ComponentInfo(ImmutableDataObject):
    name: Name
    address: Address
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    queries: Sequence[QueryBinding]
    actions: Sequence[ActionBinding]
    layout: Layout | None


class UnitInfo(ImmutableDataObject):
    name: str
    config: UnitConfig
    components: Sequence[ComponentInfo]


api = APIRouter()


def use_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


def use_environment(connection: HTTPConnection) -> Environment:
    return use_engine(connection).environment


@api.get("/config", tags=["engine"])
async def get_config(engine: Engine = Depends(use_engine)) -> Config:
    return engine.config


@api.post("/reload", tags=["engine"])
async def reload(
    response: Response,
    engine: Engine = Depends(use_engine),
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


@api.get("/messages", tags=["data"])
async def get_messages(
    query: GetMessagesQueryParameters = Depends(),
    environment: Environment = Depends(use_environment),
) -> list[Message]:
    return await environment.get_messages(query)


class GetAlertsQueryParameters(AlertQuery):
    source: Address | None = None
    level: AlertLevel | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)


@api.get("/alerts", tags=["data"])
async def get_alerts(
    query: GetAlertsQueryParameters = Depends(),
    environment: Environment = Depends(use_environment),
) -> list[Alert]:
    return await environment.get_alerts(query)


class GetStatisticsQueryParameters(StatisticsQuery):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    query: GetStatisticsQueryParameters = Depends(),
    environment: Environment = Depends(use_environment),
) -> Statistics:
    return await environment.get_statistics(query)


@api.websocket("/message-stream")
async def message_stream(
    socket: WebSocket,
    source: Address | None = None,
    search: str | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    if search:
        search = search.lower()

    try:
        await socket.accept()

        async for event in engine.events:
            if not isinstance(event, (MessageSentEvent, MessageReceivedEvent)):
                continue
            if source is not None and event.message.source != source:
                continue
            if search is not None:
                if (
                    search not in event.message.timestamp.isoformat(" ")
                    and search not in event.message.direction
                    and search.encode() not in event.message.content.lower()
                ):
                    continue

            await socket.send_text(jsonify(event.message))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.websocket("/alert-stream")
async def alert_stream(
    socket: WebSocket,
    source: Address | None = None,
    search: str | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for event in engine.events:
            if not isinstance(event, AlertEmittedEvent):
                continue
            if source is not None and event.alert.source != source:
                continue
            if search is not None:
                if (
                    search not in event.alert.timestamp.isoformat(" ")
                    and search not in event.alert.code
                    and search not in event.alert.info
                ):
                    continue

            await socket.send_text(jsonify(event.alert))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.get("/units/{unit}", tags=["units"])
async def get_unit_info(
    unit: Name,
    engine: Engine = Depends(use_engine),
    environment: Environment = Depends(use_environment),
) -> UnitInfo:
    config = engine.config.get_unit(unit)
    if config is None:
        raise HTTPException(404)

    components = []
    for component in config.components:
        components.append(
            await get_component_info(
                unit,
                component.name,
                engine,
            )
        )

    return UnitInfo(
        name=config.name,
        config=config,
        components=components,
    )


@api.get("/units/{unit}/components/{component}", tags=["components"])
async def get_component_info(
    unit: Name,
    component: Name,
    engine: Engine = Depends(use_engine),
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
        queries=list(component_cls.get_query_bindings().values()),
        actions=list(component_cls.get_action_bindings().values()),
        layout=component_cls.get_layout(),
    )


@api.post("/units/{unit}/components/{component}/procedures/{procedure}/call", tags=["procedures"])
async def call(
    unit: Name,
    component: Name,
    procedure: Name,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    try:
        return Ok(await engine.call(Address.create(unit, component), procedure, input))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/units/{unit}/components/{component}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    unit: Name,
    component: Name,
    procedure: Name,
    input: Json[Any] = Query(None),
    engine: Engine = Depends(use_engine),
) -> None:
    await socket.accept()
    address = Address.create(unit, component)

    if not isinstance(input, Mapping | None):
        await socket.close(
            code=1008,
            reason="'input' query parameter must be unspecified, null or a valid JSON object",
        )
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
            async for output in engine.subscribe(address, procedure, input):
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
