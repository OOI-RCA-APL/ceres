import inspect
from functools import wraps
from logging import Logger
from typing import TYPE_CHECKING, Any, get_type_hints

from fastapi import APIRouter, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_400_BAD_REQUEST
from uvicorn.config import Config as UvicornConfig
from uvicorn.server import Server as BaseUvicorn

from ..address import ComponentAddress
from ..component import (
    ActionBinding,
    Component,
    JobBinding,
    ProcedureBinding,
    QueryBinding,
)
from ..config import ComponentConfig, Config, ServerConfig, UnitConfig
from ..console import Console
from ..data import simplify
from ..errors import ProcedureError, ReloadError
from ..result import Fail, Ok, Result
from . import logs
from .component import load_component_cls
from .tasklet import Tasklet
from .utilities import unreachable

if TYPE_CHECKING:
    from ..engine import Engine


class Server(Tasklet):
    class Uvicorn(BaseUvicorn):
        async def serve(self, sockets: Any = None) -> None:
            logs.setup()
            await super().serve(sockets)

        def install_signal_handlers(self) -> None:
            # Don't install anything, this will be handled externally.
            pass

    def __init__(
        self,
        config: ServerConfig,
        engine: "Engine",
    ):
        self._config = config
        self._engine = engine
        self._uvicorn: Server.Uvicorn | None = None

    @property
    def config(self) -> ServerConfig:
        return self._config

    @property
    def engine(self) -> "Engine":
        return self._engine

    @property
    def logger(self) -> Logger:
        return logs.get("uvicorn")

    async def __run__(self) -> None:
        self._uvicorn = Server.Uvicorn(
            UvicornConfig(
                app=self._generate_app(),
                port=self.config.port,
                loop="none",
            )
        )

        await self._uvicorn.serve()

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

        api.include_router(self._generate_units_router(), prefix="/units")
        return api

    def _generate_units_router(self) -> APIRouter:
        units = APIRouter()

        for unit_config in self._engine.config.units:
            unit = APIRouter(prefix=f"/{unit_config.name}")

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
            input = [*args, *kwargs.values()][0] if kwargs else None

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
        except Exception:
            self.logger.error(
                f"Failed to get return type hint for {procedure.kind} {method}. No API route will be generated."
            )
            return

        response_model = Result[return_type_hint, ProcedureError]

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
