import asyncio
import inspect
from datetime import datetime
from functools import wraps
from logging import Logger
from typing import TYPE_CHECKING, Any, get_type_hints
from uuid import UUID

from fastapi import APIRouter, FastAPI, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_400_BAD_REQUEST
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn
from websockets.exceptions import ConnectionClosedError

from ..address import ComponentAddress, UnitAddress
from ..alert import Alert
from ..component import (
    ActionBinding,
    Component,
    JobBinding,
    ProcedureBinding,
    QueryBinding,
)
from ..config import ComponentConfig, Config, ServerConfig, UnitConfig
from ..data import DataObject, jsonify, simplify
from ..datetime import utc
from ..errors import ProcedureError, ReloadError
from ..message import Message
from ..result import Fail, Ok, Result
from ..stream import Stream
from . import logs
from .component import load_component_cls
from .console import Console
from .database.manager import DatabaseManager
from .tasklet import Tasklet
from .utilities import unreachable

if TYPE_CHECKING:
    from ..engine import Engine


class UnitInfo(DataObject):
    id: UUID
    config: UnitConfig


class ComponentInfo(DataObject):
    id: UUID
    config: ComponentConfig


class Server(Tasklet):
    def __init__(
        self,
        config: ServerConfig,
        engine: "Engine",
        database: DatabaseManager,
    ):
        self._config = config
        self._engine = engine
        self._database = database
        self._message_stream: Stream[Message] = Stream()
        self._alert_stream: Stream[Alert] = Stream()
        self._uvicorn: Uvicorn | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def engine(self) -> "Engine":
        return self._engine

    @property
    def database(self) -> DatabaseManager:
        return self._database

    @property
    def logger(self) -> Logger:
        return logs.get("uvicorn")

    async def __run__(self) -> None:
        await asyncio.gather(
            self._process_uvicorn(),
            self._process_messages(),
            self._process_alerts(),
        )

    async def _process_uvicorn(self) -> None:
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=self._generate_app(),
                port=self.config.port,
                loop="none",
            )
        )

        await self._uvicorn.serve()

    async def _process_messages(self) -> None:
        cursor = utc()

        while True:
            await asyncio.sleep(0.1)
            messages = await self._database.entities.get_messages(
                where=lambda message: message.timestamp > cursor,
                order_by=lambda message: message.timestamp.desc(),
            )

            if not messages:
                continue

            for message in reversed(messages):
                self._message_stream.put(message)

            cursor = messages[0].timestamp

    async def _process_alerts(self) -> None:
        cursor = utc()

        while True:
            await asyncio.sleep(0.1)
            alerts = await self._database.entities.get_alerts(
                where=lambda message: message.timestamp > cursor,
                order_by=lambda message: message.timestamp.desc(),
            )

            if not alerts:
                continue

            for alert in reversed(alerts):
                self._alert_stream.put(alert)

            cursor = alerts[0].timestamp

    async def __stop__(self) -> None:
        if self._uvicorn is not None:
            await self._uvicorn.shutdown()
            self._uvicorn = None

    def _generate_app(self) -> FastAPI:
        app = FastAPI(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
        )

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        app.include_router(self._generate_api_router(), prefix="/api")
        app.mount("/", Console(), name="console")
        return app

    def _generate_api_router(self) -> APIRouter:
        api = APIRouter()

        @api.on_event("startup")
        def startup() -> None:
            logs.setup()

        @api.get("/config", response_model=Config, tags=["engine"])
        async def config() -> Config:
            return self._engine.config

        @api.post("/reload", response_model=Result[Config, ReloadError], tags=["engine"])
        async def reload(response: Response) -> Result[Config, ReloadError]:
            match await self._engine.reload():
                case Ok(config):
                    return Ok(config)
                case Fail(error):
                    response.status_code = HTTP_400_BAD_REQUEST
                    return Fail(error)

            unreachable()

        @api.get("/messages", response_model=list[Message])
        async def messages(
            component_id: UUID | None = None,
            before: datetime | None = None,
            after: datetime | None = None,
            limit: int = Query(default=100, ge=0, le=100),
        ) -> list[Message]:
            return await self._database.entities.get_messages(
                where=lambda message: (
                    (message.connection_id == component_id) | (component_id is None)
                )
                & (before is None or message.timestamp < before)
                & (after is None or message.timestamp > after),
                order_by=lambda message: message.timestamp,
                limit=limit,
            )

        @api.websocket("/message-stream")
        async def message_stream(socket: WebSocket, component_id: UUID | None = None) -> None:
            try:
                await socket.accept()

                async for message in self._message_stream:
                    if component_id is not None and message.connection_id != component_id:
                        continue
                    await socket.send_text(jsonify(message))
            except (WebSocketDisconnect, ConnectionClosedError):
                pass

        @api.get("/alerts", response_model=list[Alert])
        async def alerts(
            origin_id: UUID | None = None,
            before: datetime | None = None,
            after: datetime | None = None,
            limit: int = Query(default=100, ge=0, le=100),
        ) -> list[Alert]:
            return await self._database.entities.get_alerts(
                where=lambda alert: ((alert.origin_id == origin_id) | (origin_id is None))
                & (before is None or alert.timestamp < before)
                & (after is None or alert.timestamp > after),
                order_by=lambda alert: alert.timestamp,
                limit=limit,
            )

        @api.websocket("/alert-stream")
        async def alert_stream(socket: WebSocket, origin_id: UUID | None = None) -> None:
            try:
                await socket.accept()

                async for alert in self._alert_stream:
                    if origin_id is not None and alert.origin_id != origin_id:
                        continue

                    await socket.send_text(jsonify(alert))
            except (WebSocketDisconnect, ConnectionClosedError):
                pass

        api.include_router(self._generate_units_router(), prefix="/units")
        return api

    def _generate_units_router(self) -> APIRouter:
        units = APIRouter()

        for unit_config in self._engine.config.units:
            unit = APIRouter(prefix=f"/{unit_config.name}")

            @unit.get("", response_model=UnitInfo)
            async def get() -> UnitInfo:
                id = await self._database.entities.get_address_id(UnitAddress(unit_config.name))
                return UnitInfo(
                    id=id,
                    config=unit_config,
                )

            unit.include_router(
                self._generate_components_router(unit_config),
                prefix="/components",
                tags=["components"],
            )
            units.include_router(unit)

        return units

    def _generate_components_router(self, unit_config: UnitConfig) -> APIRouter:
        components = APIRouter()

        for component_config in unit_config.components:
            components.include_router(
                self._generate_component_router(unit_config, component_config),
                prefix=f"/{component_config.name}",
            )

        return components

    def _generate_component_router(
        self,
        unit_config: UnitConfig,
        component_config: ComponentConfig,
    ) -> APIRouter:
        component = APIRouter()

        @component.get("", response_model=ComponentInfo)
        async def get() -> ComponentInfo:
            id = await self._database.entities.get_address_id(
                ComponentAddress(unit_config.name, component_config.name)
            )
            return ComponentInfo(
                id=id,
                config=component_config,
            )

        match load_component_cls(Component, component_config):
            case Ok(component_cls):
                pass
            case Fail():
                return component

        procedures = [
            *component_cls.get_query_bindings().values(),
            *component_cls.get_action_bindings().values(),
            *component_cls.get_job_bindings().values(),
        ]

        for procedure in procedures:
            self._register_procedure(
                component,
                unit_config,
                component_config,
                component_cls,
                procedure,
            )

        return component

    def _register_procedure(
        self,
        router: APIRouter,
        unit_config: UnitConfig,
        component_config: ComponentConfig,
        component_cls: type[Component],
        procedure: ProcedureBinding,
    ) -> None:
        match procedure:
            case QueryBinding():
                term = "queries"
            case ActionBinding():
                term = "actions"
            case JobBinding():
                term = "jobs"

        path = f"/{term}/{procedure.name}"

        instance = component_cls.__new__(component_cls)
        if (method := getattr(instance, procedure.function, None)) is None:
            self.logger.error(
                f"Failed to access {procedure.kind} method named '{procedure.function}'. No API route will be generated generation."
            )
            return

        @wraps(method)
        async def post(*args: Any, **kwargs: Any) -> Any:
            input = next(*args, *kwargs.values()) if args or kwargs else None

            result = simplify(
                await self._engine.call(
                    ComponentAddress(unit_config.name, component_config.name),
                    procedure.kind,
                    procedure.name,
                    input,
                )
            )

            return result

        try:
            return_type_hint: Any = get_type_hints(method)["return"]
            response_model = Result[return_type_hint, ProcedureError]
        except Exception:
            self.logger.error(
                f"Failed to get valid return type hint for {procedure.kind} {method}. No API route will be generated."
            )
            return

        original_signature = inspect.signature(method)
        modified_signature = original_signature.replace(  # type: ignore
            return_annotation=response_model
        )

        post.__signature__ = modified_signature  # type: ignore

        router.add_api_route(
            path=path,
            endpoint=post,
            methods=["POST"],
            response_model=response_model,
        )


class Uvicorn(BaseUvicorn):
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass
