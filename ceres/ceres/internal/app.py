import asyncio
from asyncio import CancelledError
from datetime import datetime
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
from pydantic import Json
from starlette.requests import HTTPConnection
from starlette.status import HTTP_400_BAD_REQUEST
from websockets.exceptions import ConnectionClosed

from ..address import GlobalComponentAddress, UnitAddress, caddr
from ..alert import Alert
from ..config import ComponentConfig, Config, UnitConfig
from ..data import ImmutableDataObject, jsonify
from ..database import Database
from ..database.entity import EntityManager
from ..errors import ProcedureError, ReloadError
from ..events import AlertEmittedEvent, MessageReceivedEvent, MessageSentEvent
from ..message import Message, MessageDirection
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
from .utilities import NameStr, escape_like_expression

if TYPE_CHECKING:
    from ..engine import Engine
else:
    Engine = "Engine"


class ComponentInfo(ImmutableDataObject):
    id: UUID
    name: str
    config: ComponentConfig
    queries: Sequence[QueryBinding]
    actions: Sequence[ActionBinding]
    jobs: Sequence[JobBinding]
    subscriptions: Sequence[SubscriptionBinding]
    displays: Sequence[DisplayBinding]


class UnitInfo(ImmutableDataObject):
    id: UUID
    name: str
    config: UnitConfig
    components: Sequence[ComponentInfo]


api = APIRouter()


def use_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


def use_database(connection: HTTPConnection) -> Database:
    return use_engine(connection).database


def use_entities(connection: HTTPConnection) -> EntityManager:
    return use_database(connection).entities


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


@api.get("/messages", tags=["data"])
async def get_messages(
    component_id: UUID | None = None,
    search: bytes | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    direction: MessageDirection | None = None,
    limit: int = Query(default=100, ge=0, le=500),
    entities: EntityManager = Depends(use_entities),
) -> list[Message]:
    return list(
        reversed(
            await entities.get_messages(
                where=lambda message: (
                    (message.component_id == component_id) | (component_id is None)
                )
                & (
                    search is None
                    or message.content.ilike(b"%" + escape_like_expression(search) + b"%")
                )
                & (direction is None or message.direction == direction)
                & (before is None or message.timestamp < before)
                & (after is None or message.timestamp > after),
                order_by=lambda message: message.timestamp.desc(),
                limit=limit,
            )
        )
    )


@api.get("/alerts", tags=["data"])
async def get_alerts(
    component_id: UUID | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = Query(default=100, ge=0, le=500),
    entities: EntityManager = Depends(use_entities),
) -> list[Alert]:
    return list(
        reversed(
            await entities.get_alerts(
                where=lambda alert: ((alert.component_id == component_id) | (component_id is None))
                & (before is None or alert.timestamp < before)
                & (after is None or alert.timestamp > after),
                order_by=lambda alert: alert.timestamp,
                limit=limit,
            )
        )
    )


@api.websocket("/message-stream")
async def message_stream(
    socket: WebSocket,
    component_id: UUID | None = None,
    search: bytes | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for event in engine.events:
            if not isinstance(event, (MessageSentEvent, MessageReceivedEvent)):
                continue
            if component_id is not None and event.message.component_id != component_id:
                continue

            if search is not None:
                if search not in event.message.content:
                    continue

            await socket.send_text(jsonify(event.message))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.websocket("/alert-stream")
async def alert_stream(
    socket: WebSocket,
    component_id: UUID | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for event in engine.events:
            if not isinstance(event, AlertEmittedEvent):
                continue
            if component_id is not None and event.alert.component_id != component_id:
                continue

            await socket.send_text(jsonify(event.alert))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.get("/units/{unit}", tags=["units"])
async def get_unit_info(
    unit: NameStr,
    engine: Engine = Depends(use_engine),
    entities: EntityManager = Depends(use_entities),
) -> UnitInfo:
    address = UnitAddress(unit)
    config = engine.config.get_unit(address)
    if config is None:
        raise HTTPException(404)

    components = []
    for component in config.components:
        components.append(
            await get_component_info(
                unit,
                component.name,
                engine,
                entities,
            )
        )

    id = await entities.get_address_id(address)
    return UnitInfo(
        id=id,
        name=address.name,
        config=config,
        components=components,
    )


@api.get("/units/{unit}/components/{component}", tags=["components"])
async def get_component_info(
    unit: NameStr,
    component: NameStr,
    engine: Engine = Depends(use_engine),
    entities: EntityManager = Depends(use_entities),
) -> ComponentInfo:
    address = caddr(unit, component)
    component_config = engine.config.get_component(address)
    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(404)

    id = await entities.get_address_id(address)
    return ComponentInfo(
        id=id,
        name=address.name,
        config=component_config,
        queries=list(component_cls.get_query_bindings().values()),
        actions=list(component_cls.get_action_bindings().values()),
        jobs=list(component_cls.get_job_bindings().values()),
        subscriptions=list(component_cls.get_subscription_bindings().values()),
        displays=list(component_cls.get_display_bindings().values()),
    )


async def _call(
    engine: Engine,
    unit: NameStr,
    component: NameStr,
    kind: CallableProcedureKind,
    procedure: NameStr,
    input: Mapping[str, object] | None,
) -> Result[object | None, ProcedureError]:
    return await engine.call(GlobalComponentAddress(unit, component), kind, procedure, input)


@api.post("/units/{unit}/components/{component}/queries/{query}", tags=["procedures"])
async def run_query(
    unit: NameStr,
    component: NameStr,
    query: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.QUERY, query, input)


@api.post("/units/{unit}/components/{component}/actions/{action}", tags=["procedures"])
async def run_action(
    unit: NameStr,
    component: NameStr,
    action: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.ACTION, action, input)


@api.post("/units/{unit}/components/{component}/jobs/{job}", tags=["procedures"])
async def run_job(
    unit: NameStr,
    component: NameStr,
    job: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[Any | None, ProcedureError]:
    return await _call(engine, unit, component, CallableProcedureKind.JOB, job, input)


async def _subscribe(
    engine: Engine,
    socket: WebSocket,
    unit: NameStr,
    component: NameStr,
    kind: SubscribableProcedureKind,
    procedure: NameStr,
    input: Json[Any],
) -> None:
    await socket.accept()
    address = caddr(unit, component)

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
                code=1008,
                reason=jsonify(fail),
            )
            return

    async def write() -> None:
        async for value in values:
            await socket.send_text(jsonify(value))

    write_task = asyncio.create_task(write(), name="write")

    try:
        while True:
            await socket.receive_text()
    except (WebSocketDisconnect, ConnectionClosed, CancelledError):
        pass
    finally:
        write_task.cancel()


@api.websocket("/units/{unit}/components/{component}/subscriptions/{subscription}")
async def run_subscription(
    socket: WebSocket,
    unit: NameStr,
    component: NameStr,
    subscription: NameStr,
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
    unit: NameStr,
    component: NameStr,
    display: NameStr,
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
