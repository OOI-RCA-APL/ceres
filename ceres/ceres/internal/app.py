from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, final
from uuid import UUID

from fastapi import (
    APIRouter,
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
from .console import Console
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


api = APIRouter()


def use_engine(request: Request) -> Engine:
    assert isinstance(request.app, App)
    return request.app.engine


def use_database(request: Request) -> DatabaseManager:
    return use_engine(request).database


def use_entities(request: Request) -> EntityManager:
    return use_database(request).entities


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
    except (WebSocketDisconnect, ConnectionClosedError):
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
    except (WebSocketDisconnect, ConnectionClosedError):
        pass


@api.get("/units/:unit", response_model=UnitInfo, tags=["units"])
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
