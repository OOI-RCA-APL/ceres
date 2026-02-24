import json
import warnings
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, cast, override
from uuid import UUID

import jwt.warnings
from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
    params,
)
from fastapi.requests import HTTPConnection
from fastapi.websockets import WebSocketState
from pydantic import AfterValidator, Json, ValidationError
from pydantic_core import PydanticKnownError
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED

from ceres._internal import util
from ceres._internal.entity import BaseEntityFilter
from ceres.data import DataObject, DateTime, StrEnum, adapt, to_json, validate
from ceres.error import Failure, NotAuthenticatedError, NotFoundError, NotPermittedError
from ceres.timing import utc
from ceres.user import User, UserRole

# Allow using short JWT secrets without warnings.
warnings.filterwarnings("ignore", category=jwt.warnings.InsecureKeyLengthWarning, module="jwt")

if TYPE_CHECKING:
    from enum import Enum

    from asgiref.typing import WebSocketReceiveEvent
    from pydantic.main import IncEx

    from ceres._internal.app.main import App
    from ceres._internal.server import Server
    from ceres.config import ServerAuthenticationConfig
    from ceres.engine import Engine
    from ceres.message import BoundMessageManager, MessageFilter
    from ceres.record import Record
else:
    Engine = object
    App = object


def exclude_recursively(fields: Iterable[str]) -> IncEx:
    exclude: dict[str, Any] = {field: True for field in fields}
    exclude["__all__"] = exclude
    return exclude


EXCLUDE_PASSWORDS: IncEx = exclude_recursively(["password"])


class Router(APIRouter):
    @override
    def __init__(
        self,
        *,
        prefix: str = "",
        tags: list[str | Enum] | None = None,
        dependencies: list[params.Depends] | None = None,
        default_response_model_include: IncEx | None = None,
        default_response_model_exclude: IncEx | None = None,
    ) -> None:
        super().__init__(
            prefix=prefix,
            tags=tags,
            dependencies=dependencies,
        )
        self.default_response_model_include = default_response_model_include
        self.default_response_model_exclude = default_response_model_exclude

    @override
    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        response_model_include: IncEx | None = None,
        response_model_exclude: IncEx | None = None,
        **kwargs: Any,
    ) -> None:
        if response_model_include is None:
            response_model_include = self.default_response_model_include
        if response_model_exclude is None:
            response_model_exclude = self.default_response_model_exclude

        super().add_api_route(
            path,
            endpoint,
            response_model_include=response_model_include,
            response_model_exclude=response_model_exclude,
            **kwargs,
        )


def _get_current_app(connection: HTTPConnection) -> App:
    return connection.app


CurrentApp = Annotated[App, Depends(_get_current_app)]


def _get_current_engine(app: CurrentApp) -> Engine:
    return app.engine


type CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


def _get_current_cli(app: CurrentApp) -> bool:
    return app.cli


type CurrentCLI = Annotated[bool, Depends(_get_current_cli)]


class SocketDirection(StrEnum):
    SEND = "send"
    RECEIVE = "receive"
    BOTH = "both"


@dataclass
class Socket:
    socket: WebSocket
    server: Server

    async def send(self, data: Any) -> None:
        await self.socket.send_text(to_json(data))

    async def receive(self) -> Any:
        message = cast("WebSocketReceiveEvent", await self.socket.receive())
        data: bytes | str | None = message.get("text")
        if data is None:
            data = message.get("bytes")
        if data is None:
            raise ValueError("Invalid message format.")

        return json.loads(data)

    async def execute(
        self,
        callback: Callable[[], Coroutine[Any, Any, Any]],
        direction: SocketDirection = SocketDirection.SEND,
    ) -> None:
        async def run():
            try:
                await callback()
            except RuntimeError:
                return

        async def wait_disconnect():
            if direction == SocketDirection.SEND:
                # If we're only sending data, poll the socket for disconnects.
                while True:
                    try:
                        await self.socket.receive()
                    except RuntimeError:
                        break
            else:
                # Otherwise, do nothing.
                await util.sleep_forever()

        await util.wait_any(
            run(),
            wait_disconnect(),
            self.server.wait_until_stopping(),
            cancelling=True,
            raised=True,
        )

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        await self.socket.close(code, reason)


async def _use_current_socket(socket: WebSocket, engine: CurrentEngine) -> AsyncIterator[Socket]:
    assert engine.server is not None
    try:
        try:
            await socket.accept()
        except RuntimeError:
            pass

        yield Socket(socket, engine.server)
    except WebSocketDisconnect:
        pass
    finally:
        if socket.application_state == WebSocketState.CONNECTED:
            await socket.close()


type CurrentSocket = Annotated[Socket, Depends(_use_current_socket)]


def _get_procedure_query_arguments(
    arguments: Annotated[Json[Any], Query()] = None,
) -> Mapping[str, object]:
    adapter = adapt(Mapping[str, object])

    try:
        if arguments is None:
            return {}
        if isinstance(arguments, str):
            return adapter.validate_json(arguments)
        return adapter.validate_python(arguments)
    except Exception:
        raise HTTPException(
            HTTP_400_BAD_REQUEST,
            "'arguments' query parameter must be unspecified, null or a valid JSON object",
        )


type CurrentProcedureQueryArguments = Annotated[
    Mapping[str, object] | None, Depends(_get_procedure_query_arguments)
]


class Identity(DataObject):
    token: str
    expires: DateTime
    user: User


def create_identity(
    user: User,
    authentication: ServerAuthenticationConfig,
) -> Identity:
    import jwt

    expires = utc() + authentication.duration
    token = jwt.encode(
        {
            "sub": str(user.id),
            "exp": expires,
        },
        authentication.secret,
        "HS256",
    )

    return Identity(
        user=user,
        token=token,
        expires=expires,
    )


class AuthorizationCookieType(StrEnum):
    INSECURE = "insecure"
    SECURE = "secure"


def assign_authorization_cookie(
    response: Response,
    identity: Identity,
    type: AuthorizationCookieType,
) -> None:
    secure = type == AuthorizationCookieType.SECURE
    response.set_cookie(
        "Authorization",
        f"Bearer {identity.token}",
        expires=identity.expires,
        secure=secure,
        httponly=secure,
    )


type CurrentAuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
type CurrentAuthorizationCookie = Annotated[str | None, Cookie(alias="Authorization")]


async def _get_current_identity(
    engine: CurrentEngine,
    authorization_header: CurrentAuthorizationHeader = None,
    authorization_cookie: CurrentAuthorizationCookie = None,
) -> Identity | None:
    from jwt import InvalidTokenError

    authentication = engine.config.server.authentication
    if authentication is None:
        return None

    authorization = authorization_header or authorization_cookie
    if authorization is None:
        return None

    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
        try:
            import jwt

            info: Mapping[str, object] = jwt.decode(
                token,
                authentication.secret,
                ["HS256"],
            )
        except InvalidTokenError:
            return None

        id = info.get("sub")
        expires = info.get("exp")
        if id is None or expires is None:
            return None

        try:
            id = UUID(str(id))
        except ValueError:
            return None

        try:
            expires = validate(expires, datetime if TYPE_CHECKING else DateTime)
        except ValidationError:
            return None

        user = await engine.users.get(id)
        if user is None:
            return None

        return Identity(
            token=token,
            expires=expires,
            user=user,
        )


type CurrentIdentity = Annotated[Identity | None, Depends(_get_current_identity)]


def _get_required_identity(identity: CurrentIdentity) -> Identity:
    if identity is None:
        raise Failure(NotAuthenticatedError)

    return identity


type RequireIdentity = Annotated[Identity, Depends(_get_required_identity)]


async def _get_current_user(identity: CurrentIdentity) -> User | None:
    if identity is None:
        return None

    return identity.user


type CurrentUser = Annotated[User | None, Depends(_get_current_user)]


async def _require_current_user(user: CurrentUser) -> User:
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return user


type RequireUser = Annotated[User, Depends(_require_current_user)]


def _get_current_role(user: CurrentUser, cli: CurrentCLI) -> UserRole | None:
    if cli:
        return UserRole.ADMIN
    if user is None:
        return None
    return user.role


type CurrentRole = Annotated[UserRole | None, Depends(_get_current_role)]


def _restrict(
    required: UserRole,
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    if engine.config.server.authentication is None:
        # Authentication is disabled, so allow all users.
        return None
    if cli:
        # The CLI is functionally an admin, and so can do anything.
        return None

    if user is None:
        raise Failure(NotAuthenticatedError)
    if user.disabled or role < required:
        raise Failure(NotPermittedError)

    return user


def _require_viewer(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.VIEWER, engine, user, cli, role)


def _require_operator(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.OPERATOR, engine, user, cli, role)


def _require_admin(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.ADMIN, engine, user, cli, role)


VIEWER = Depends(_require_viewer)
OPERATOR = Depends(_require_operator)
ADMIN = Depends(_require_admin)

type RequireViewer = Annotated[User | None, VIEWER]
type RequireOperator = Annotated[User | None, OPERATOR]
type RequireAdmin = Annotated[User | None, ADMIN]


def assert_found[T](value: T | None, /) -> T:
    if value is None:
        raise Failure(NotFoundError)

    return value


def create_record_get_route(router: Router, Record: type[Record]):
    naming = Record.__naming__

    async def get(engine: CurrentEngine, id: UUID):
        filter = cast("type[MessageFilter]", Record.Filter)(id=id)
        return assert_found(await engine.__manager__(Record).where(filter).first())

    get.__name__ = f"get_{util.snakecase(naming.singular)}"
    return router.get(
        "/{id:uuid}",
        response_model=Record,
        dependencies=[VIEWER],
        tags=[util.kebabcase(naming.plural)],
    )(get)


def create_record_get_all_route(router: Router, Record: type[Record], limit: int):
    naming = Record.__naming__

    async def get_all(
        engine: CurrentEngine,
        filter: Annotated[
            Record.Filter,  # type: ignore
            Query(),
            Limit(limit),
        ],
    ):
        return await engine.__manager__(Record).where(filter)

    get_all.__name__ = f"get_all_{util.snakecase(naming.plural)}"
    return router.get(
        "",
        response_model=list[Record],
        dependencies=[VIEWER],
        tags=[util.kebabcase(naming.plural)],
    )(get_all)


def create_record_count_route(router: Router, Record: type[Record]):
    naming = Record.__naming__

    async def count(
        engine: CurrentEngine,
        filter: Annotated[Record.Filter, Query()],  # type: ignore
    ) -> int:
        return await engine.__manager__(Record).where(filter).count()

    count.__name__ = f"count_{util.snakecase(naming.plural)}"
    return router.get(
        "/count",
        dependencies=[VIEWER],
        tags=[util.kebabcase(naming.plural)],
    )(count)


def create_record_stream_route(router: Router, Record: type[Record]):
    naming = Record.__naming__

    async def stream(
        socket: CurrentSocket,
        engine: CurrentEngine,
        filter: Annotated[Record.Filter, Query()],  # type: ignore
    ) -> None:
        manager = cast("BoundMessageManager", engine.__manager__(Record))

        async def write() -> None:
            async for record in manager.stream.where(cast("Any", filter)):
                await socket.send(record)

        await socket.execute(write)

    stream.__name__ = f"stream_{util.snakecase(naming.plural)}"
    return router.websocket("", dependencies=[VIEWER])(stream)


def create_record_router(name: str, Record: type[Record], *, limit: int = 1000):
    router = Router(prefix=f"/{name}", tags=[name])

    create_record_get_route(router, Record)
    create_record_get_all_route(router, Record, limit)
    create_record_count_route(router, Record)
    create_record_stream_route(router, Record)

    return router


def _require_self_or_admin(
    connection: HTTPConnection,
    user: RequireViewer,
    role: CurrentRole,
) -> UUID:
    user_id = connection.path_params.get("user_id") or connection.path_params.get("id")
    if user_id is None:
        raise Failure(NotPermittedError)

    try:
        user_id = UUID(str(user_id))
    except ValueError:
        raise Failure(NotPermittedError)

    if role < UserRole.ADMIN:
        if user is None or user.id != user_id:
            raise Failure(NotPermittedError)

    return user_id


SELF_OR_ADMIN = Depends(_require_self_or_admin)


def Limit[FilterT: BaseEntityFilter](max: int) -> AfterValidator:
    """
    Decorator to validate limits for a filter.

    :param default: Default limit if not specified.
    :param max: Maximum limit allowed.
    """

    def validate_limit(filter: FilterT) -> FilterT:
        if filter.limit is None:
            filter = filter.model_copy(update={"limit": max})
        elif filter.limit > max:
            raise PydanticKnownError("less_than_equal", {"le": max})

        return filter

    return AfterValidator(validate_limit)
