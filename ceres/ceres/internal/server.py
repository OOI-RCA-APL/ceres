import inspect
from functools import wraps
from logging import Logger
from typing import TYPE_CHECKING, Any, Callable, cast, get_type_hints

from fastapi import APIRouter, FastAPI, Response
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
from ..config import Config, ServerConfig
from ..data import simplify
from ..errors import ProcedureError, ReloadError
from ..result import Fail, Ok, Result
from . import logs
from .component import load_component_cls
from .tasklet import Tasklet
from .utilities import awaitify, unreachable

if TYPE_CHECKING:
    from ..engine import Engine


class Server(Tasklet):
    def __init__(
        self,
        config: ServerConfig,
        engine: "Engine",
    ):
        self._config = config
        self._engine = engine
        self._uvicorn: Uvicorn | None = None

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
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=self.generate_app(),
                port=self.config.port,
                loop="none",
            )
        )

        await self._uvicorn.serve()

    async def __stop__(self) -> None:
        if self._uvicorn is not None:
            await self._uvicorn.shutdown()
            self._uvicorn = None

    def generate_app(self) -> FastAPI:
        app = FastAPI(redoc_url=None)
        api = APIRouter(prefix="/api")

        def presimplify(function: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(function)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return simplify(await awaitify(function(*args, **kwargs)))

            return wrapper

        def register_procedure(
            router: APIRouter,
            component: object,
            address: ComponentAddress,
            procedure: ProcedureBinding,
        ) -> None:
            if (method := getattr(component, procedure.function, None)) is None:
                self.logger.error(
                    f"Failed to access {procedure.kind} method named '{procedure.function}'. No API route will be generated generation."
                )
                return

            @wraps(method)
            async def endpoint(*args: Any, **kwargs: Any) -> Any:
                input = [*args, *kwargs.values()][0] if kwargs else None

                result = simplify(
                    await self._engine.call(
                        address,
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
            endpoint.__signature__ = inspect.signature(method).replace(  # type: ignore
                return_annotation=response_model
            )

            match procedure:
                case QueryBinding():
                    term = "queries"
                case ActionBinding():
                    term = "actions"
                case JobBinding():
                    term = "jobs"
                case _:
                    return

            path = f"/{term}/{procedure.name}"

            router.add_api_route(
                path=path,
                endpoint=endpoint,
                methods=["POST"],
                response_model=response_model,
            )

        @api.on_event("startup")
        def startup() -> None:
            logs.setup()

        @api.get(
            "/config",
            response_model=Config,
            tags=["engine"],
        )
        @presimplify
        async def config() -> Config:
            return self._engine.config

        @api.post(
            "/reload",
            response_model=cast(Any, Result[Config, ReloadError]),
            tags=["engine"],
        )
        @presimplify
        async def reload(response: Response) -> Result[Config, ReloadError]:
            match await self._engine.reload():
                case Ok(config):
                    return Ok(config)
                case Fail(error):
                    response.status_code = HTTP_400_BAD_REQUEST
                    return Fail(error)

            unreachable()

        units = APIRouter(prefix="/units")

        for unit_config in self._engine.config.units:
            unit = APIRouter(prefix=f"/{unit_config.name}")
            components = APIRouter(prefix="/components", tags=["components"])

            for component_config in unit_config.components:
                component = APIRouter(prefix=f"/{component_config.name}")

                match load_component_cls(Component, component_config):
                    case Ok(component_cls):
                        pass
                    case Fail():
                        continue

                component_instance = component_cls.__new__(component_cls)
                procedures = [
                    *component_cls.get_query_bindings().values(),
                    *component_cls.get_action_bindings().values(),
                    *component_cls.get_job_bindings().values(),
                ]

                for procedure in procedures:
                    register_procedure(
                        component,
                        component_instance,
                        ComponentAddress(unit_config.name, component_config.name),
                        procedure,
                    )

                components.include_router(component)

            unit.include_router(components)
            units.include_router(unit)

        api.include_router(units)
        app.include_router(api)

        return app


class Uvicorn(BaseUvicorn):
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass
