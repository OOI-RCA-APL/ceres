import asyncio
from asyncio import CancelledError
from enum import Enum
from typing import TYPE_CHECKING, Any, Mapping, Sequence, final
from uuid import UUID

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

from ..address import Address
from ..alert import Alert
from ..component import Component
from ..config import ComponentConfig, Config, UnitConfig
from ..data import ImmutableDataObject, Name, jsonify
from ..environment import AlertQuery, Environment, MessageQuery
from ..errors import ProcedureError, ReloadError
from ..events import AlertEmittedEvent, MessageReceivedEvent, MessageSentEvent
from ..message import Message
from ..procedure import (
    ActionBinding,
    CallableProcedureKind,
    DisplayBinding,
    JobBinding,
    QueryBinding,
    SubscribableProcedureKind,
    SubscriptionBinding,
)
from ..result import Fail, Ok, Result
from . import logs
from .console import Console
from .utilities import strify

if TYPE_CHECKING:
    from ..engine import Engine
else:
    Engine = "Engine"


class ComponentRole(str, Enum):
    CONNECTION = "connection"
    DISPATCHER = "dispatcher"
    NOTIFIER = "notifier"


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ..connection import Connection
    from ..dispatcher import Dispatcher
    from ..notifier import Notifier

    roles: list[ComponentRole] = []
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, Dispatcher):
        roles.append(ComponentRole.DISPATCHER)
    if issubclass(component, Notifier):
        roles.append(ComponentRole.NOTIFIER)

    return roles


class ComponentInfo(ImmutableDataObject):
    id: UUID
    name: Name
    address: Address
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    queries: Sequence[QueryBinding]
    actions: Sequence[ActionBinding]
    jobs: Sequence[JobBinding]
    subscriptions: Sequence[SubscriptionBinding]
    displays: Sequence[DisplayBinding]


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
    limit: int = Field(default=100, ge=0, le=500)


@api.get("/messages", tags=["data"])
async def get_messages(
    query: GetMessagesQueryParameters = Depends(),
    environment: Environment = Depends(use_environment),
) -> list[Message]:
    return await environment.get_messages(query)


class GetAlertsQueryParameters(AlertQuery):
    limit: int = Field(default=100, ge=0, le=500)


@api.get("/alerts", tags=["data"])
async def get_alerts(
    query: GetAlertsQueryParameters = Depends(),
    environment: Environment = Depends(use_environment),
) -> list[Alert]:
    return await environment.get_alerts(query)


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
    address: Address | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for event in engine.events:
            if not isinstance(event, AlertEmittedEvent):
                continue
            if address is not None and event.alert.source != address:
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
                environment,
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
    environment: Environment = Depends(use_environment),
) -> ComponentInfo:
    address = Address.create(unit, component)
    component_config = engine.config.get_component(address)
    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(404)

    id = await environment.get_component_id(address)
    return ComponentInfo(
        id=id,
        name=component,
        address=address,
        config=component_config,
        roles=_get_component_roles(component_cls),
        queries=list(component_cls.get_query_bindings().values()),
        actions=list(component_cls.get_action_bindings().values()),
        jobs=list(component_cls.get_job_bindings().values()),
        subscriptions=list(component_cls.get_subscription_bindings().values()),
        displays=list(component_cls.get_display_bindings().values()),
    )


async def _call(
    engine: Engine,
    unit: Name,
    component: Name,
    kind: CallableProcedureKind,
    procedure: Name,
    input: Mapping[str, object] | None,
) -> Result[object | None, ProcedureError]:
    return await engine.call(Address.create(unit, component), kind, procedure, input)


@api.post("/units/{unit}/components/{component}/queries/{query}", tags=["procedures"])
async def run_query(
    unit: Name,
    component: Name,
    query: Name,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.QUERY, query, input)


@api.post("/units/{unit}/components/{component}/actions/{action}", tags=["procedures"])
async def run_action(
    unit: Name,
    component: Name,
    action: Name,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.ACTION, action, input)


@api.post("/units/{unit}/components/{component}/jobs/{job}", tags=["procedures"])
async def run_job(
    unit: Name,
    component: Name,
    job: Name,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.JOB, job, input)


async def _subscribe(
    engine: Engine,
    socket: WebSocket,
    unit: Name,
    component: Name,
    kind: SubscribableProcedureKind,
    procedure: Name,
    input: Json[Any],
) -> None:
    await socket.accept()
    address = Address.create(unit, component)

    if not isinstance(input, Mapping | None):
        await socket.close(
            code=1008,
            reason="'input' query parameter must be unspecified, null or a valid JSON object",
        )
        return

    match await engine.subscribe(address, kind, procedure, input):
        case Ok(values):
            pass
        case Fail() as fail:
            await socket.close(
                code=1008,  # Set code for policy violation.
                reason=jsonify(fail),
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
            async for value in values:
                await socket.send_text(jsonify(value))
        except Exception as exception:
            try:
                await socket.close(
                    code=1011,  # Set code for internal error.
                    reason=jsonify(strify(exception)[0:100]),
                )
            except Exception:
                pass
        finally:
            task_read.cancel()

    task_read = asyncio.create_task(read(), name="read")
    task_write = asyncio.create_task(write(), name="write")

    try:
        await asyncio.gather(task_read, task_write)
    except CancelledError:
        pass


@api.websocket("/units/{unit}/components/{component}/subscriptions/{subscription}")
async def run_subscription(
    socket: WebSocket,
    unit: Name,
    component: Name,
    subscription: Name,
    input: Json[Any] = Query(None),
    engine: Engine = Depends(use_engine),
) -> None:
    await _subscribe(
        engine,
        socket,
        unit,
        component,
        SubscribableProcedureKind.SUBSCRIPTION,
        subscription,
        input,
    )


@api.websocket("/units/{unit}/components/{component}/displays/{display}")
async def run_display(
    socket: WebSocket,
    unit: Name,
    component: Name,
    display: Name,
    input: Json[Any] = Query(None),
    engine: Engine = Depends(use_engine),
) -> None:
    await _subscribe(
        engine,
        socket,
        unit,
        component,
        SubscribableProcedureKind.DISPLAY,
        display,
        input,
    )


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
        self.mount("/", Console(), name="console")
