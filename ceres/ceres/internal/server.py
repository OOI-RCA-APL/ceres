from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generic,
    Literal,
    TypeVar,
    cast,
    get_type_hints,
)

from fastapi import APIRouter, FastAPI, Response
from pydantic.generics import GenericModel
from starlette.status import HTTP_400_BAD_REQUEST
from typing_extensions import Self
from uvicorn import Config as UvicornConfig
from uvicorn import Server as UvicornServer

from ..address import ComponentAddress
from ..component import ActionBinding, Component, QueryBinding
from ..config import ComponentConfig, Config, ServerConfig, UnitConfig
from ..errors import ReloadError
from ..result import Fail, Ok
from ..utilities import awaitify, simplify
from . import logs
from .component import load_component_cls
from .tasklet import Tasklet
from .utilities import unreachable

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
        self._uvicorn = Uvicorn(
            UvicornConfig(
                app=create_app(engine),
                port=config.port,
                loop="none",
            )
        )

    async def __run__(self) -> None:
        await self._uvicorn.serve()

    async def __stop__(self) -> None:
        if hasattr(self._uvicorn, "servers"):
            await self._uvicorn.shutdown()


class Uvicorn(UvicornServer):  # type: ignore
    async def serve(self, sockets: Any = None) -> None:
        logs.setup()
        await super().serve(sockets)

    def install_signal_handlers(self) -> None:
        # Don't install anything, this will be handled externally.
        pass


SuccessDataT = TypeVar("SuccessDataT")
ErrorDataT = TypeVar("ErrorDataT")


class Success(GenericModel, Generic[SuccessDataT]):
    status: Literal["ok"] = "ok"
    data: SuccessDataT

    @classmethod
    def create(cls, data: SuccessDataT) -> Self:
        return Success(data=data)


class Error(GenericModel, Generic[ErrorDataT]):
    status: Literal["error"] = "error"
    data: ErrorDataT

    @classmethod
    def create(cls, data: ErrorDataT) -> Self:
        return Error(data=data)


def presimplify(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        return simplify(await awaitify(function(*args, **kwargs)))

    return wrapper


def create_app(engine: "Engine") -> FastAPI:
    app = FastAPI()
    api = APIRouter()

    @api.on_event("startup")
    def startup() -> None:
        logs.setup()

    @api.get("/config", response_model=Config)
    @presimplify
    async def config() -> Config:
        return engine.config

    @api.post(
        "/reload",
        response_model=cast(Any, Success[Config] | Error[ReloadError]),
    )
    @presimplify
    async def reload(response: Response) -> Success[Config] | Error[ReloadError]:
        match await engine.reload():
            case Ok(config):
                return Success.create(config)
            case Fail(error):
                response.status_code = HTTP_400_BAD_REQUEST
                return Error.create(error)

        unreachable()

    def register(
        router: APIRouter,
        address: ComponentAddress,
        binding: ActionBinding | QueryBinding,
    ) -> None:
        if (method := getattr(instance, binding.function.__name__, None)) is None:
            return

        match binding:
            case ActionBinding():
                term = "actions"
            case QueryBinding():
                term = "queries"

        path = f"/units/{address.unit}/components/{address.name}/{term}/{binding.name}"
        try:
            model = get_type_hints(method).get("return")
        except Exception:
            return

        match term:
            case "actions":

                @router.post(path, response_model=model)
                @wraps(method)
                async def action_endpoint(*args: Any, **kwargs: Any) -> Any:
                    return await engine.call_action(
                        address,
                        binding.name,
                        kwargs,
                    )

            case "queries":

                @router.get(path, response_model=model)
                @wraps(method)
                async def query_endpoint(*args: Any, **kwargs: Any) -> Any:
                    return await engine.call_query(
                        address,
                        binding.name,
                        kwargs,
                    )

    for unit_config in engine.config.units:
        for component_config in unit_config.components:
            match load_component_cls(Component, component_config):
                case Ok(cls):
                    pass
                case Fail():
                    continue

            instance = cls.__new__(cls)
            actions = cls.get_action_bindings()
            queries = cls.get_query_bindings()

            for binding in [*actions.values(), *queries.values()]:
                register(
                    api,
                    ComponentAddress(unit_config.name, component_config.name),
                    binding,
                )

    app.include_router(api, prefix="/api")
    return app
