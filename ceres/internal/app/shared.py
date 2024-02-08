from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Annotated, Any, AsyncIterator, Mapping
from uuid import UUID

import jwt
from fastapi import (
    Cookie,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.requests import HTTPConnection
from jwt import InvalidTokenError
from pydantic import Json, ValidationError
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_401_UNAUTHORIZED
from websockets.exceptions import ConnectionClosed

from ceres.config import ServerAuthenticationConfig
from ceres.data import DateTime, ImmutableDataObject, jsonify
from ceres.internal.utilities import StrEnum, get_type_adapter
from ceres.timing import utc
from ceres.user import User, UserRole

if TYPE_CHECKING:
    from ceres.engine import Engine
    from ceres.internal.app.main import App
else:
    Engine = object
    App = object


def _get_current_app(connection: HTTPConnection) -> App:
    return connection.app


CurrentApp = Annotated[App, Depends(_get_current_app)]


def _get_current_engine(app: CurrentApp) -> Engine:
    return app.engine


CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


def _get_current_cli(app: CurrentApp) -> bool:
    return app.cli


CurrentCLI = Annotated[bool, Depends(_get_current_cli)]


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


class PrivateIdentity(ImmutableDataObject):
    user: User
    token: str
    expires: DateTime


class Identity(PrivateIdentity):
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


async def _get_current_identity(
    engine: CurrentEngine,
    authorization_cookie: str | None = Cookie(None, alias="Authorization"),
    authorization_header: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Identity | None:
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
            expires = get_type_adapter(DateTime).validate_python(expires)
        except ValidationError:
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


VIEWER = Depends(partial(_restrict, role=UserRole.VIEWER))
OPERATOR = Depends(partial(_restrict, role=UserRole.OPERATOR))
ADMIN = Depends(partial(_restrict, role=UserRole.ADMIN))

RequireViewer = Annotated[User | None, VIEWER]
RequireOperator = Annotated[User | None, OPERATOR]
RequireAdmin = Annotated[User | None, ADMIN]
