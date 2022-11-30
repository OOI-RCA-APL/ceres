from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from starlette.status import HTTP_400_BAD_REQUEST
from websockets.exceptions import ConnectionClosedError

from ..address import ComponentAddress, UnitAddress
from ..alert import Alert
from ..component import ProcedureKind
from ..config import ComponentConfig, Config, UnitConfig
from ..data import DataObject, jsonify
from ..errors import Error, ProcedureError, ReloadError
from ..message import Message
from ..result import Fail, Ok, Result
from . import logs
from .database.entity import EntityManager
from .database.manager import DatabaseManager
from .utilities import NameStr

if TYPE_CHECKING:
    from ..engine import Engine
else:
    Engine = "Engine"


class UnitInfo(DataObject):
    id: UUID
    config: UnitConfig


class ComponentInfo(DataObject):
    id: UUID
    config: ComponentConfig


router = APIRouter()


def use_engine(request: Request) -> Engine:
    return request.app.state.engine


def use_database(request: Request) -> DatabaseManager:
    return use_engine(request).database


def use_entities(request: Request) -> EntityManager:
    return use_database(request).entities


@router.on_event("startup")
def startup() -> None:
    logs.setup()


@router.get("/config", response_model=Config, tags=["engine"])
async def get_config(engine: Engine = Depends(use_engine)) -> Config:
    return engine.config


@router.post("/reload", response_model=Result[Config, ReloadError], tags=["engine"])
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


@router.get("/messages", response_model=list[Message], tags=["data"])
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
                    (message.connection_id == component_id) | (component_id is None)
                )
                & (before is None or message.timestamp < before)
                & (after is None or message.timestamp > after),
                order_by=lambda message: message.timestamp.desc(),
                limit=limit,
            )
        )
    )


@router.get("/alerts", response_model=list[Alert], tags=["data"])
async def get_alerts(
    origin_id: UUID | None = None,
    before: datetime | None = None,
    after: datetime | None = None,
    limit: int = Query(default=100, ge=0, le=100),
    entities: EntityManager = Depends(use_entities),
) -> list[Alert]:
    return list(
        reversed(
            await entities.get_alerts(
                where=lambda alert: ((alert.origin_id == origin_id) | (origin_id is None))
                & (before is None or alert.timestamp < before)
                & (after is None or alert.timestamp > after),
                order_by=lambda alert: alert.timestamp,
                limit=limit,
            )
        )
    )


@router.websocket("/message-stream")
async def message_stream(
    socket: WebSocket,
    component_id: UUID | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for message in engine.message_stream:
            if component_id is not None and message.connection_id != component_id:
                continue
            await socket.send_text(jsonify(message))
    except (WebSocketDisconnect, ConnectionClosedError):
        pass


@router.websocket("/alert-stream")
async def alert_stream(
    socket: WebSocket,
    origin_id: UUID | None = None,
    engine: Engine = Depends(use_engine),
) -> None:
    try:
        await socket.accept()

        async for alert in engine.alert_stream:
            if origin_id is not None and alert.origin_id != origin_id:
                continue

            await socket.send_text(jsonify(alert))
    except (WebSocketDisconnect, ConnectionClosedError):
        pass


@router.get("/units/:unit", response_model=UnitInfo, tags=["units"])
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


@router.get(
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
    config = engine.config.get_component(address)
    if config is None:
        raise HTTPException(404)
    id = await entities.get_address_id(address)
    return ComponentInfo(id=id, config=config)


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


@router.post(
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


@router.post(
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


@router.post(
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
