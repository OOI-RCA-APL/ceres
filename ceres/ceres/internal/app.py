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
from starlette.requests import HTTPConnection
from starlette.status import HTTP_400_BAD_REQUEST
from websockets.exceptions import ConnectionClosed

from ..address import ComponentAddress, UnitAddress
from ..alert import Alert
from ..component import ActionBinding, JobBinding, ProcedureKind, QueryBinding
from ..config import ComponentConfig, Config, UnitConfig
from ..data import ImmutableDataObject, jsonify
from ..errors import Error, ProcedureCancelledError, ProcedureError, ReloadError
from ..message import Message
from ..result import Fail, Ok, Result
from . import logs
from .console import Console
from .database.entity import EntityManager
from .database.manager import DatabaseManager
from .utilities import NameStr

if TYPE_CHECKING:
    from ..engine import Engine
else:
    Engine = "Engine"


class UnitInfo(ImmutableDataObject):
    id: UUID
    config: UnitConfig


class ComponentInfo(ImmutableDataObject):
    id: UUID
    config: ComponentConfig
    queries: Sequence[QueryBinding]
    actions: Sequence[ActionBinding]
    jobs: Sequence[JobBinding]


api = APIRouter()


def use_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


def use_database(connection: HTTPConnection) -> DatabaseManager:
    return use_engine(connection).database


def use_entities(connection: HTTPConnection) -> EntityManager:
    return use_database(connection).entities


@api.get("/config", response_model=Config, tags=["engine"])
async def get_config(engine: Engine = Depends(use_engine)) -> Config:
    return engine.config


@api.post("/reload", response_model=Result[Config, ReloadError], tags=["engine"])
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


@api.get("/messages", response_model=list[Message], tags=["data"])
async def get_messages(
    component_id: UUID | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = Query(default=100, ge=0, le=100),
    entities: EntityManager = Depends(use_entities),
) -> list[Message]:
    return list(
        reversed(
            await entities.get_messages(
                where=lambda message: (
                    (message.component_id == component_id) | (component_id is None)
                )
                & (before is None or message.timestamp < before)
                & (after is None or message.timestamp > after),
                order_by=lambda message: message.timestamp.desc(),
                limit=limit,
            )
        )
    )


@api.get("/alerts", response_model=list[Alert], tags=["data"])
async def get_alerts(
    component_id: UUID | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = Query(default=100, ge=0, le=100),
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
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for message in engine.message_stream:
            if component_id is not None and message.component_id != component_id:
                continue
            await socket.send_text(jsonify(message))
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

        async for alert in engine.alert_stream:
            if component_id is not None and alert.component_id != component_id:
                continue

            await socket.send_text(jsonify(alert))
    except (WebSocketDisconnect, ConnectionClosed):
        pass


@api.get("/units/{unit}", response_model=UnitInfo, tags=["units"])
async def get_unit_info(
    unit: NameStr,
    engine: Engine = Depends(use_engine),
    entities: EntityManager = Depends(use_entities),
) -> UnitInfo:
    address = UnitAddress(unit)
    config = engine.config.get_unit(address)
    if config is None:
        raise HTTPException(404)
    id = await entities.get_address_id(address)
    return UnitInfo(id=id, config=config)


@api.get(
    "/units/{unit}/components/{component}",
    response_model=ComponentInfo,
    tags=["components"],
)
async def get_component_info(
    unit: NameStr,
    component: NameStr,
    engine: Engine = Depends(use_engine),
    entities: EntityManager = Depends(use_entities),
) -> ComponentInfo:
    address = ComponentAddress(unit, component)
    component_config = engine.config.get_component(address)
    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(404)
    id = await entities.get_address_id(address)
    return ComponentInfo(
        id=id,
        config=component_config,
        queries=list(component_cls.get_query_bindings().values()),
        actions=list(component_cls.get_action_bindings().values()),
        jobs=list(component_cls.get_job_bindings().values()),
    )


async def _run_procedure(
    engine: Engine,
    unit: NameStr,
    component: NameStr,
    kind: ProcedureKind,
    procedure: NameStr,
    input: Mapping[str, object] | None,
) -> Result[object | None, ProcedureError]:
    address = ComponentAddress(unit, component)
    return await engine.call(address, kind, procedure, input)


@api.post(
    "/units/{unit}/components/{component}/queries/{query}",
    response_model=Result[Any | None, Error],
    tags=["procedures"],
)
async def run_query(
    unit: NameStr,
    component: NameStr,
    query: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[object | None, ProcedureError]:
    return await _run_procedure(engine, unit, component, ProcedureKind.QUERY, query, input)


@api.post(
    "/units/{unit}/components/{component}/actions/{action}",
    response_model=Result[Any | None, Error],
    tags=["procedures"],
)
async def run_action(
    unit: NameStr,
    component: NameStr,
    action: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[object | None, ProcedureError]:
    return await _run_procedure(engine, unit, component, ProcedureKind.ACTION, action, input)


@api.post(
    "/units/{unit}/components/{component}/jobs/{job}",
    response_model=Result[Any | None, Error],
    tags=["procedures"],
)
async def run_job(
    unit: NameStr,
    component: NameStr,
    job: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> Result[object | None, ProcedureError]:
    return await _run_procedure(engine, unit, component, ProcedureKind.JOB, job, input)


@api.websocket("/units/{unit}/components/{component}/subscriptions/{subscription}")
async def run_subscription(
    socket: WebSocket,
    unit: NameStr,
    component: NameStr,
    subscription: NameStr,
    input: Mapping[str, object] | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    await socket.accept()

    try:
        address = ComponentAddress(unit, component)

        match await engine.subscribe(address, subscription, input):
            case Ok(values):
                pass
            case Fail() as fail:
                await socket.close(reason=jsonify(fail))
                return

        try:
            async for value in values:
                await socket.send_text(jsonify(value))
        except CancelledError:
            await socket.close(reason=jsonify(Fail(ProcedureCancelledError())))
    except (WebSocketDisconnect, ConnectionClosed):
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
        self.mount("/", Console(), name="console")
