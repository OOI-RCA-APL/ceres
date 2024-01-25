import asyncio
import json
import traceback
from asyncio import CancelledError
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from http.client import responses
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Sequence,
    cast,
    final,
)
from uuid import UUID

import jwt
from asgiref.typing import (
    ASGIReceiveCallable,
    ASGIReceiveEvent,
    ASGISendCallable,
    ASGISendEvent,
    HTTPScope,
    Scope,
    WebSocketScope,
)
from fastapi import (
    APIRouter,
    Body,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from pydantic import Field, Json
from starlette.requests import HTTPConnection
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from websockets.exceptions import ConnectionClosed

from ceres.address import Address
from ceres.alert import Alert, Level
from ceres.component import Component, ProcedureBinding, Status
from ceres.config import (
    ComponentConfig,
    Config,
    ConsoleConfig,
    DatabaseConfig,
    ServerAuthenticationConfig,
    ServerConfig,
    ServiceConfig,
)
from ceres.data import DateTime, ImmutableDataObject, Name, jsonify
from ceres.errors import (
    ProcedureComponentDoesNotExistError,
    ProcedureError,
    ProcedureInternalError,
    ReloadError,
)
from ceres.exceptions import ProcedureException
from ceres.filter import (
    AlertFilter,
    ComponentFilter,
    LogEntryFilter,
    MessageFilter,
    StatisticsFilter,
)
from ceres.internal import logs
from ceres.internal.auth import validate_password
from ceres.internal.console import ConsoleFiles
from ceres.internal.utilities import StrEnum, get_type_adapter, strify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.object import Statistics
from ceres.result import Fail, Ok, Result
from ceres.timing import utc
from ceres.user import PrivateUser, User, UserRole

if TYPE_CHECKING:
    from ceres.engine import Engine
else:
    Engine = object


class ComponentRole(StrEnum):
    CONNECTION = "connection"
    INTERFACE = "interface"


def _get_component_roles(component: Component | type[Component]) -> Sequence[ComponentRole]:
    if not isinstance(component, type):
        component = type(component)

    from ceres.roles.connection import Connection
    from ceres.roles.interface import Interface

    roles: list[ComponentRole] = []
    if issubclass(component, Connection):
        roles.append(ComponentRole.CONNECTION)
    if issubclass(component, Interface):
        roles.append(ComponentRole.INTERFACE)

    return roles


class ComponentInfo(ImmutableDataObject):
    name: Name
    address: Address
    components: Sequence["ComponentInfo"]
    config: ComponentConfig
    roles: Sequence[ComponentRole]
    procedures: Sequence[ProcedureBinding]


ComponentInfo.model_rebuild()

api = APIRouter()


def _get_current_engine(connection: HTTPConnection) -> Engine:
    assert isinstance(connection.app, App)
    return connection.app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


@dataclass
class Socket:
    socket: WebSocket

    async def send(self, data: Any) -> None:
        await self.socket.send_text(jsonify(data))

    async def receive(self) -> Any:
        await self.socket.receive_json()


async def _use_current_socket(socket: WebSocket) -> AsyncIterator[Socket]:
    try:
        await socket.accept()
        yield Socket(socket)
    except (WebSocketDisconnect, ConnectionClosed):
        pass


CurrentSocket = Annotated[Socket, Depends(_use_current_socket)]


def _get_procedure_query_arguments(
    query_arguments: Annotated[Json[Any], Query(alias="arguments")] = None,
) -> Mapping[str, object]:
    adapter = get_type_adapter(Mapping[str, object])

    try:
        if query_arguments is None:
            return {}
        if isinstance(query_arguments, str):
            return adapter.validate_json(query_arguments)
        return adapter.validate_python(query_arguments)
    except Exception:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'arguments' query parameter must be unspecified, null or a valid JSON object",
        )


CurrentProcedureQueryArguments = Annotated[
    Mapping[str, object], Depends(_get_procedure_query_arguments)
]


class Identity(ImmutableDataObject):
    user: User
    token: str
    expires: DateTime


def _create_identity(
    user: User,
    authentication: ServerAuthenticationConfig,
) -> Identity:
    expires = utc() + authentication.duration
    token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": expires,
        },
        authentication.secret,
    )

    return Identity(
        user=user,
        token=token,
        expires=expires,
    )


async def _get_current_identity(
    engine: CurrentEngine,
    authorization: str = Header(None),
) -> Identity | None:
    authentication = engine.config.server.authentication
    if authentication is None:
        return None

    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        try:
            info: dict[str, Any] = jwt.decode(token, secret=authentication.secret)
        except Exception:
            return None

        id = info.get("sub")
        expires = info.get("exp")
        if id is None or expires is None:
            return None

        try:
            id = UUID(id)
        except Exception:
            return None

        try:
            expires = get_type_adapter(DateTime).validate_python(expires)
        except Exception:
            return None

        user = await engine.get_user(id=id)
        if user is None:
            return None

        return Identity(
            user=user,
            token=token,
            expires=expires,
        )


CurrentIdentity = Annotated[Identity | None, Depends(_get_current_identity)]


def _get_required_identity(identity: CurrentIdentity) -> Identity:
    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return identity


RequireIdentity = Annotated[Identity, Depends(_get_required_identity)]


async def _get_current_user(identity: CurrentIdentity) -> User | None:
    if identity is None:
        return None

    return identity.user


CurrentUser = Annotated[User | None, Depends(_get_current_user)]


def _restrict(
    connection: HTTPConnection,
    engine: CurrentEngine,
    user: CurrentUser,
    role: UserRole,
) -> User | None:
    assert isinstance(connection.app, App)

    if engine.config.server.authentication is None:
        # Authentication is disabled, so allow all users.
        return None
    if connection.app.cli:
        # The CLI is functionally an admin, so can do anything.
        return None
    if user is None or user.disabled or user.role < role:
        # If there is no current user, the user is disabled, or the user's role is insufficient,
        # deny access.
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return user


RequireViewer = Annotated[User | None, Depends(partial(_restrict, role=UserRole.VIEWER))]
RequireOperator = Annotated[User | None, Depends(partial(_restrict, role=UserRole.OPERATOR))]
RequireAdmin = Annotated[User | None, Depends(partial(_restrict, role=UserRole.OPERATOR))]


class MeResult(ImmutableDataObject):
    user: PrivateUser
    expires: DateTime


@api.get("/me", tags=["auth"])
async def me(identity: CurrentIdentity) -> MeResult:
    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return MeResult(
        user=identity.user,
        expires=identity.expires,
    )


class LoginResult(Identity):
    pass


@api.get("/login", tags=["auth"])
async def login(
    engine: CurrentEngine,
    username: str,
    password: str,
) -> LoginResult:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise HTTPException(HTTP_403_FORBIDDEN)

    user = await engine.get_user(username=username)
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)
    if not validate_password(password, user.hash):
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    identity = _create_identity(user, authentication)
    return LoginResult(
        user=identity.user,
        token=identity.token,
        expires=identity.expires,
    )


class RefreshResult(Identity):
    pass


@api.get("/refresh", tags=["auth"])
async def refresh(
    engine: CurrentEngine,
    identity: CurrentIdentity,
) -> RefreshResult:
    authentication = engine.config.server.authentication
    if authentication is None:
        raise HTTPException(HTTP_403_FORBIDDEN)

    if identity is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    user = await engine.get_user(id=identity.user.id)
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    identity = _create_identity(user, authentication)
    return RefreshResult(
        user=identity.user,
        token=identity.token,
        expires=identity.expires,
    )


@api.get("/config", tags=["config"], dependencies=[Depends(RequireOperator)])
async def get_config(engine: CurrentEngine) -> Config:
    return engine.config


@api.get("/config/service", tags=["config"], dependencies=[Depends(RequireOperator)])
async def get_service_config(engine: CurrentEngine) -> ServiceConfig:
    return engine.config.service


@api.get("/config/server", tags=["config"], dependencies=[Depends(RequireOperator)])
async def get_server_config(engine: CurrentEngine) -> ServerConfig:
    return engine.config.server


@api.get("/config/console", tags=["config"])
async def get_console_config(engine: CurrentEngine) -> ConsoleConfig:
    return engine.config.console


@api.get("/config/database", tags=["config"], dependencies=[Depends(RequireOperator)])
async def get_database_config(engine: CurrentEngine) -> DatabaseConfig:
    return engine.config.database


@api.post("/reload", tags=["engine"], dependencies=[Depends(RequireOperator)])
async def reload(engine: CurrentEngine, response: Response) -> Result[Config, ReloadError]:
    match await engine.reload():
        case Ok(config):
            return Ok(config)
        case Fail(error):
            response.status_code = HTTP_400_BAD_REQUEST
            return Fail(error)


class StartResult(ImmutableDataObject):
    started: Sequence[Address]


@api.post("/start", tags=["components"], dependencies=[Depends(RequireOperator)])
async def start(engine: CurrentEngine, filter: ComponentFilter) -> StartResult:
    stopped = engine.get_components(filter, running=False)
    stopped.start()
    return StartResult(started=[component.address for component in stopped])


class StopResult(ImmutableDataObject):
    stopped: Sequence[Address]


@api.post("/stop", tags=["components"], dependencies=[Depends(RequireOperator)])
async def stop(engine: CurrentEngine, filter: ComponentFilter) -> StopResult:
    running = engine.get_components(filter, running=True)
    await running.stop()
    return StopResult(stopped=[component.address for component in running])


class EnableResult(ImmutableDataObject):
    enabled: Sequence[Address]


@api.post("/enable", tags=["components"], dependencies=[Depends(RequireOperator)])
async def enable(engine: CurrentEngine, filter: ComponentFilter) -> EnableResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()
    return EnableResult(enabled=[component.address for component in disabled])


class DisableResult(ImmutableDataObject):
    disabled: Sequence[Address]


@api.post("/disable", tags=["components"], dependencies=[Depends(RequireOperator)])
async def disable(engine: CurrentEngine, filter: ComponentFilter) -> DisableResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()
    return DisableResult(disabled=[component.address for component in enabled])


class UpResult(ImmutableDataObject):
    enabled: Sequence[Address]
    started: Sequence[Address]


@api.post("/up", tags=["components"], dependencies=[Depends(RequireOperator)])
async def up(engine: CurrentEngine, filter: ComponentFilter) -> UpResult:
    disabled = engine.get_components(filter, enabled=False)
    await disabled.enable()

    stopped = engine.get_components(filter, running=False)
    stopped.start()

    return UpResult(
        enabled=[component.address for component in disabled],
        started=[component.address for component in stopped],
    )


class DownResult(ImmutableDataObject):
    disabled: Sequence[Address]
    stopped: Sequence[Address]


@api.post("/down", tags=["components"], dependencies=[Depends(RequireOperator)])
async def down(engine: CurrentEngine, filter: ComponentFilter) -> DownResult:
    enabled = engine.get_components(filter, enabled=True)
    await enabled.disable()

    running = engine.get_components(filter, running=True)
    await running.stop()

    return DownResult(
        disabled=[component.address for component in enabled],
        stopped=[component.address for component in running],
    )


@api.get("/components/{address}", tags=["components"])
async def get_component(engine: CurrentEngine, address: Address) -> ComponentInfo:
    component_config = engine.config.get_component(address)
    if component_config is not None and type(component_config) is not ComponentConfig:
        component_config = ComponentConfig.model_validate(
            {
                "name": component_config.name,
                "class": component_config.cls,
                "arguments": component_config.arguments,
                "components": component_config.components,
            }
        )

    component_cls = engine.config.get_component_cls(address)
    if component_config is None or component_cls is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    children: list[ComponentInfo] = []
    for child_config in component_config.components:
        children.append(await get_component(engine, address / child_config.name))

    try:
        info = ComponentInfo(
            name=component_config.name,
            address=address,
            config=component_config,
            roles=_get_component_roles(component_cls),
            procedures=list(component_cls.get_procedure_bindings().values()),
            components=children,
        )
        return info
    except Exception:
        traceback.print_exc()
        raise


@api.get("/status/{address}?", tags=["status"])
async def get_status(engine: CurrentEngine, address: Address | None = None) -> Status:
    component = engine.get_component(address)
    if component is None:
        raise HTTPException(HTTP_404_NOT_FOUND)

    return await component.get_status()


class GetStatusesQueryParameters(ComponentFilter):
    pass


@api.get("/statuses", tags=["status"])
async def get_statuses(
    engine: CurrentEngine,
    filter: Annotated[GetStatusesQueryParameters, Depends()],
) -> list[Status]:
    return await engine.get_statuses(filter)


class StreamStatusesQueryParameters(GetStatusesQueryParameters):
    pass


@api.websocket("/statuses")
async def stream_statuses(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamStatusesQueryParameters, Depends()],
) -> None:
    async for statuses in engine.stream_statuses(filter):
        await socket.send(statuses)


class GetMessagesQueryParameters(MessageFilter):
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/messages", tags=["messages"])
async def get_messages(
    engine: CurrentEngine,
    filter: Annotated[GetMessagesQueryParameters, Depends()],
) -> list[Message]:
    return await engine.get_messages(filter)


class StreamMessagesQueryParameters(GetMessagesQueryParameters):
    pass


@api.websocket("/messages")
async def stream_messages(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamMessagesQueryParameters, Depends()],
) -> None:
    async for message in engine.stream_messages(filter):
        await socket.send(message)


class GetAlertsQueryParameters(AlertFilter):
    level: Level | None = None
    code: str | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/alerts", tags=["alerts"])
async def get_alerts(
    engine: CurrentEngine,
    filter: Annotated[GetAlertsQueryParameters, Depends()],
) -> list[Alert]:
    return await engine.get_alerts(filter)


class StreamAlertsQueryParameters(GetAlertsQueryParameters):
    pass


@api.websocket("/alerts")
async def stream_alerts(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamAlertsQueryParameters, Depends()],
) -> None:
    async for alert in engine.stream_alerts(filter):
        await socket.send(alert)


class GetLogEntriesQueryParameters(LogEntryFilter):
    level: Level | None = None
    limit: int = Field(default=100, ge=0, le=1000)
    offset: int = Field(default=0, ge=0)


@api.get("/log-entries", tags=["logs"])
async def get_log_entries(
    engine: CurrentEngine,
    filter: Annotated[GetLogEntriesQueryParameters, Depends()],
) -> list[LogEntry]:
    return await engine.get_log_entries(filter)


class StreamLogEntriesQueryParameters(GetLogEntriesQueryParameters):
    pass


@api.websocket("/log-entries")
async def stream_log_entries(
    socket: CurrentSocket,
    engine: CurrentEngine,
    filter: Annotated[StreamLogEntriesQueryParameters, Depends()],
) -> None:
    async for entry in engine.stream_log_entries(filter):
        await socket.send(entry)


class GetStatisticsQueryParameters(StatisticsFilter):
    pass


@api.get("/statistics", tags=["data"])
async def get_statistics(
    engine: CurrentEngine,
    filter: Annotated[GetStatisticsQueryParameters, Depends()],
) -> list[Statistics]:
    return await engine.get_statistics(filter)


@api.api_route(
    "/components/{address}/procedures/{procedure}/call",
    methods=["GET", "POST"],
    tags=["procedures"],
)
async def call(
    request: Request,
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
    body_arguments: Mapping[Name, object] | None = Body(None),
) -> Result[Any | None, ProcedureError]:
    if isinstance(query_arguments, str):
        try:
            query_arguments = json.loads(query_arguments)
        except Exception:
            raise HTTPException(
                HTTP_400_BAD_REQUEST,
                "'arguments' query parameter must be unspecified, null or a valid JSON object",
            )

    if not isinstance(query_arguments, Mapping | None):
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'arguments' query parameter must be unspecified, null or a valid JSON object",
        )

    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(body_arguments or {})
    arguments.update(request.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    try:
        component = engine.get_component(address)
        if component is None:
            return Fail(ProcedureComponentDoesNotExistError())
        return Ok(await component.call(procedure, arguments))
    except ProcedureException as exception:
        return Fail(exception.error)


@api.websocket("/components/{address}/procedures/{procedure}/subscribe")
async def subscribe(
    socket: WebSocket,
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> None:
    await socket.accept()

    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(socket.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    component = engine.get_component(address)
    if component is None:
        code = 1008  # Set code for policy violation.
        reason = jsonify(Fail(ProcedureComponentDoesNotExistError()))
        await socket.close(code, reason)
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
            async for output in component.subscribe(procedure, arguments):
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


class LoggingMiddleware:
    def __init__(self, app: "App") -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: ASGIReceiveCallable,
        send: ASGISendCallable,
    ) -> None:
        async def receive_wrapper() -> ASGIReceiveEvent:
            return await receive()

        async def send_wrapper(message: ASGISendEvent) -> None:
            from ceres.internal.app import App

            app = scope.get("app")

            if isinstance(app, App):
                try:
                    if message["type"] == "http.response.start" and scope["type"] == "http":
                        http = cast(HTTPScope, scope)  # type: ignore
                        path = http["path"]
                        verb = http["method"]
                        client = http["client"]
                        host = client[0] if client else "?"

                        status = message["status"]
                        description = responses.get(status, "Unknown")
                        level = Level.INFO if status < 400 else Level.ERROR

                        app.engine.log.write(
                            level,
                            f"[HTTP] {verb} {path} {host} {status} {description}",
                        )
                    elif (
                        message["type"] == "websocket.accept"
                        or message["type"] == "websocket.close"
                        and scope["type"] == "websocket"
                    ):
                        socket = cast(WebSocketScope, scope)  # type: ignore
                        type = message["type"]
                        path = socket["path"]
                        match type:
                            case "websocket.accept":
                                verb = "ACCEPT"
                            case "websocket.close":
                                verb = "CLOSE"
                        client = socket["client"]
                        host = client[0] if client else "?"

                        app.engine.log.info(f"[WS] '{verb}' {path} {host}")
                except Exception:
                    traceback.print_exc()

            return await send(message)

        return await self.app(scope, receive_wrapper, send_wrapper)  # type: ignore


root = APIRouter()


def _get_favicon_response(
    engine: CurrentEngine,
    suffix: str,
    media_type: str,
) -> FileResponse:
    if engine.config.console.favicon is None or engine.config.console.favicon.suffix != suffix:
        path = Path(__file__).parent / ("../static/console/favicon" + suffix)
    else:
        path = engine.config.console.favicon

    return FileResponse(path, media_type=media_type)


@root.get("/favicon.ico")
def get_favicon_ico(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".ico", "image/x-icon")


@root.get("/favicon.png")
def get_favicon_png(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".png", "image/png")


@root.get("/favicon.svg")
def get_favicon_svg(engine: CurrentEngine) -> FileResponse:
    return _get_favicon_response(engine, ".svg", "image/svg+xml")


@final
class App(FastAPI):
    def __init__(self, engine: Engine, *, cli: bool = False, **kwargs: Any) -> None:
        self.__engine = engine
        self.__cli = cli

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            logs.setup()
            yield

        super().__init__(
            redoc_url=None,
            docs_url="/api/docs",
            openapi_url="/api/openapi.json",
            lifespan=lifespan,
        )

        @self.middleware("http")
        async def error_middleware(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            try:
                return await call_next(request)
            except Exception:
                self.engine.log.error(traceback.format_exc())
                raise

        self.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.add_middleware(LoggingMiddleware)  # type: ignore
        self.add_middleware(GZipMiddleware)

        self.include_router(api, prefix="/api")
        self.include_router(root)
        self.mount("/", ConsoleFiles(), name="console")

    @property
    def engine(self) -> Engine:
        return self.__engine

    @property
    def cli(self) -> bool:
        return self.__cli
