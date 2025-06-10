from dataclasses import dataclass
from datetime import datetime
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    AsyncIterator,
    Callable,
    Coroutine,
    Mapping,
)
from uuid import UUID

from fastapi import (
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.requests import HTTPConnection
from fastapi.routing import APIRouter
from fastapi.websockets import WebSocketState
from pydantic import Field, Json, ValidationError
from starlette.requests import cookie_parser
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.record import BaseRecord
from ceres.data import (
    DateTime,
    DeferBuild,
    EmailStr,
    ImmutableDataObject,
    StrEnum,
    UsernameStr,
    jsonify,
)
from ceres.error import Failure, NotAuthenticatedError, NotFoundError, NotPermittedError
from ceres.timing import utc
from ceres.user import User, UserRole

if TYPE_CHECKING:
    from ceres._internal.app.main import App
    from ceres.engine import Engine
else:
    Engine = object
    App = object

with lazy_imports(__name__):
    import jwt

    from ceres._internal.server import Server
    from ceres.config import ServerAuthenticationConfig


def _get_current_app(connection: HTTPConnection) -> App:
    return connection.app


CurrentApp = Annotated[App, Depends(_get_current_app)]


def _get_current_engine(app: CurrentApp) -> Engine:
    return app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


def _get_current_cli(app: CurrentApp) -> bool:
    return app.cli


CurrentCLI = Annotated[bool, Depends(_get_current_cli)]


class SocketDirection(StrEnum):
    SEND = "send"
    RECEIVE = "receive"
    BOTH = "both"


@dataclass
class Socket:
    socket: WebSocket
    server: Server

    async def send(self, data: Any) -> None:
        await self.socket.send_text(jsonify(data))

    async def receive(self) -> Any:
        await self.socket.receive_json()

    async def execute(
        self,
        callback: Callable[[], Coroutine[Any, Any, Any]],
        direction: SocketDirection = SocketDirection.SEND,
    ) -> None:
        async def poll():
            if direction == SocketDirection.SEND:
                # If we're only sending data, poll the socket for disconnects.
                while True:
                    await self.socket.receive_bytes()
            else:
                # Otherwise, do nothing.
                await util.sleep_forever()

        await util.wait_any(
            callback(),
            poll(),
            self.server.wait_until_stopping(),
            cancelling=True,
            raised=True,
        )

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        await self.socket.close(code, reason)


async def _use_current_socket(socket: WebSocket, engine: CurrentEngine) -> AsyncIterator[Socket]:
    from websockets.exceptions import ConnectionClosed

    assert engine.server is not None
    try:
        await socket.accept()
        yield Socket(socket, engine.server)
    except (WebSocketDisconnect, ConnectionClosed):
        pass
    finally:
        if socket.application_state == WebSocketState.CONNECTED:
            await socket.close()


CurrentSocket = Annotated[Socket, Depends(_use_current_socket)]


def _get_procedure_query_arguments(
    arguments: Annotated[Json[Any], Query()] = None,
) -> Mapping[str, object]:
    adapter = util.get_type_adapter(Mapping[str, object])

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


CurrentProcedureQueryArguments = Annotated[
    Mapping[str, object] | None, Depends(_get_procedure_query_arguments)
]


class APIUser(ImmutableDataObject, DeferBuild):
    id: UUID
    username: UsernameStr
    email: EmailStr
    role: UserRole
    disabled: bool


APIUser.__name__ = "User"


class APIIdentity(ImmutableDataObject, DeferBuild):
    user: APIUser
    token: str
    expires: DateTime


APIIdentity.__name__ = "Identity"


class Identity(APIIdentity):
    user: User


def create_identity(
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


async def _get_current_cookies(connection: HTTPConnection) -> dict[str, str]:
    """
    Parse cookies from request headers.

    Multiple "cookie" headers, as allowed in HTTP/2, will be combined into a single dictionary, with
    later cookies with the same name overriding earlier ones.

    See https://github.com/encode/starlette/discussions/2916.
    """
    cookies: dict[str, str] = {}
    for value in connection.headers.getlist("cookie"):
        cookies.update(cookie_parser(value))

    return cookies


CurrentCookies = Annotated[dict[str, str], Depends(_get_current_cookies)]


async def _get_current_authorization_cookie(cookies: CurrentCookies) -> str | None:
    return cookies.get("Authorization")


CurrentAuthorizationHeader = Annotated[str | None, Header(alias="Authorization")]
CurrentAuthorizationCookie = Annotated[str | None, Depends(_get_current_authorization_cookie)]


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
            expires = util.get_type_adapter(
                datetime if TYPE_CHECKING else DateTime
            ).validate_python(expires)
        except ValidationError:
            return None

        user = await engine.users.get(id)
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
        raise Failure(NotAuthenticatedError)

    return identity


RequireIdentity = Annotated[Identity, Depends(_get_required_identity)]


async def _get_current_user(identity: CurrentIdentity) -> User | None:
    if identity is None:
        return None

    return identity.user


CurrentUser = Annotated[User | None, Depends(_get_current_user)]


async def _require_current_user(user: CurrentUser) -> User:
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return user


RequireUser = Annotated[User, Depends(_require_current_user)]


def _get_current_role(user: CurrentUser, cli: CurrentCLI) -> UserRole | None:
    if cli:
        return UserRole.ADMIN
    if user is None:
        return None
    return user.role


CurrentRole = Annotated[UserRole | None, Depends(_get_current_role)]


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


def __require_viewer(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.VIEWER, engine, user, cli, role)


def __require_operator(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.OPERATOR, engine, user, cli, role)


def __require_admin(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    return _restrict(UserRole.ADMIN, engine, user, cli, role)


VIEWER = Depends(__require_viewer)
OPERATOR = Depends(__require_operator)
ADMIN = Depends(__require_admin)

RequireViewer = Annotated[User | None, VIEWER]
RequireOperator = Annotated[User | None, OPERATOR]
RequireAdmin = Annotated[User | None, ADMIN]


def assert_found[T](value: T | None, /) -> T:
    if value is None:
        raise Failure(NotFoundError)

    return value


def create_record_get_route(router: APIRouter, Record: type[BaseRecord]):
    singular = util.get_entity_plural(Record)

    class QueryParameters(Record.Filter):
        pass

    QueryParameters.__name__ = f"Get{singular.title().replace(' ', '')}QueryParameters"

    async def get(engine: CurrentEngine, id: UUID):
        return assert_found(await util.get_entity_manager(engine, Record).get(id))  # type: ignore

    get.__name__ = f"Get {singular.title()}"
    return router.get("/{id:uuid}", response_model=Record)(get)


def create_record_get_all_route(router: APIRouter, Record: type[BaseRecord], limit: int):
    plural = util.get_entity_plural(Record)

    _limit = limit

    class QueryParameters(Record.Filter):
        limit: int = Field(default=100, ge=0, le=_limit)

    QueryParameters.__name__ = f"GetAll{plural.title().replace(' ', '')}QueryParameters"

    async def get_all(
        engine: CurrentEngine,
        filter: Annotated[QueryParameters, Query()],
    ):
        return await util.get_entity_manager(engine, Record).where(filter)

    get_all.__name__ = f"Get {plural.title()}"
    return router.get("", response_model=list[Record])(get_all)


def create_record_follow_route(router: APIRouter, Record: type[BaseRecord]):
    plural = util.get_entity_plural(Record)

    class QueryParameters(Record.Filter):
        pass

    QueryParameters.__name__ = f"Follow{plural.title().replace(' ', '')}QueryParameters"

    async def follow(
        socket: CurrentSocket,
        engine: CurrentEngine,
        filter: Annotated[QueryParameters, Query()],
    ) -> None:
        async def write() -> None:
            async for record in util.get_entity_manager(engine, Record).follow(filter):  # type: ignore
                await socket.send(record)

        await socket.execute(write)

    follow.__name__ = f"Follow {plural.title()}"
    return router.websocket("")(follow)


def create_record_router(name: str, Record: type[BaseRecord], *, limit: int = 1000):
    router = APIRouter(prefix=f"/{name}", tags=[name])

    create_record_get_route(router, Record)
    create_record_get_all_route(router, Record, limit)
    create_record_follow_route(router, Record)

    return router


def __require_self_or_admin(
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


SELF_OR_ADMIN = Depends(__require_self_or_admin)
