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

from ceres.__internal__.entity import BaseEntityFilter
from ceres.__internal__.utilities.case import kebabcase, snakecase
from ceres.concurrency import race, sleep
from ceres.data import DataObject, DateTime, StrEnum, adapt, from_json, to_json, validate
from ceres.error import NotAuthenticatedError, NotFoundError, NotPermittedError
from ceres.timing import utc
from ceres.user import User, UserRole

# Allow using short JWT secrets without warnings.
warnings.filterwarnings("ignore", category=jwt.warnings.InsecureKeyLengthWarning, module="jwt")

if TYPE_CHECKING:
    from enum import Enum

    from asgiref.typing import WebSocketReceiveEvent
    from pydantic.main import IncEx

    from ceres.__internal__.app.main import App
    from ceres.__internal__.server import Server
    from ceres.config import ServerAuthenticationConfig
    from ceres.engine import Engine
    from ceres.message import BoundMessageManager, MessageFilter
    from ceres.record import Record
else:
    Engine = object
    App = object


def exclude_recursively(fields: Iterable[str]) -> IncEx:
    """Build a recursive Pydantic include/exclude dict that excludes the given fields at every
    nesting level.

    Args:
        fields: Field names to exclude.

    Returns:
        A nested dict suitable for `response_model_exclude`.
    """
    exclude: dict[str, Any] = {field: True for field in fields}
    exclude["__all__"] = exclude
    return exclude


EXCLUDE_PASSWORDS: IncEx = exclude_recursively(["password"])


class Router(APIRouter):
    """An `APIRouter` subclass that supports default response model include/exclude settings.

    Routes added to this router inherit its `default_response_model_include` and
    `default_response_model_exclude` unless overridden per-route.
    """

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
        """Initialize a router with optional default include/exclude for response models.

        Args:
            prefix: URL prefix for all routes on this router.
            tags: OpenAPI tags to apply to routes.
            dependencies: Dependencies required by all routes on this router.
            default_response_model_include: Default fields to include in response serialization.
            default_response_model_exclude: Default fields to exclude from response serialization.
        """
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
        """Add an API route, falling back to the router's default include/exclude when none is
        specified on the route itself.
        """
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
    """Extract the `App` instance from the current HTTP connection's scope."""
    return connection.app


CurrentApp = Annotated[App, Depends(_get_current_app)]


def _get_current_engine(app: CurrentApp) -> Engine:
    """Extract the `Engine` from the current `App`."""
    return app.engine


type CurrentEngine = Annotated[Engine, Depends(_get_current_engine)]


def _get_current_cli(app: CurrentApp) -> bool:
    """Return whether the current request is being served in CLI mode."""
    return app.cli


type CurrentCLI = Annotated[bool, Depends(_get_current_cli)]


class SocketDirection(StrEnum):
    """Direction of data flow for a managed WebSocket session."""

    SEND = "send"
    RECEIVE = "receive"
    BOTH = "both"


@dataclass
class Socket:
    """Wrapper around a raw `WebSocket` that provides JSON serialization and lifecycle management.

    Pair with `_use_current_socket` to accept, yield, and close the socket automatically.
    """

    socket: WebSocket
    server: Server

    async def send(self, data: Any) -> None:
        """Serialize `data` to JSON and send it as a text frame."""
        await self.socket.send_text(to_json(data))

    async def receive(self) -> Any:
        """Wait for the next WebSocket message and deserialize it from JSON.

        Raises:
            ValueError: If the received message contains neither text nor bytes.
        """
        message = cast("WebSocketReceiveEvent", await self.socket.receive())
        data: bytes | str | None = message.get("text")
        if data is None:
            data = message.get("bytes")
        if data is None:
            raise ValueError("Invalid message format.")

        return from_json(data)

    async def execute(
        self,
        callback: Callable[[], Coroutine[Any, Any, Any]],
        direction: SocketDirection = SocketDirection.SEND,
    ) -> None:
        """Run `callback` concurrently with a disconnect watcher and the server shutdown signal.

        The first of these three tasks to finish cancels the others. When `direction` is
        `SEND`, the disconnect watcher actively polls the socket for close frames.

        Args:
            callback: An async callable containing the main work to perform.
            direction: The expected data-flow direction, which controls disconnect detection.
        """

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
                await sleep(...)

        await race(
            run(),
            wait_disconnect(),
            self.server.wait_until_stopping(),
            raise_exceptions=True,
        )

    async def close(self, code: int = 1000, reason: str | None = None) -> None:
        """Close the WebSocket with the given status code and optional reason."""
        await self.socket.close(code, reason)


async def _use_current_socket(socket: WebSocket, engine: CurrentEngine) -> AsyncIterator[Socket]:
    """Accept a WebSocket connection, yield a managed `Socket`, and ensure cleanup on exit."""
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
    """Parse and validate the `arguments` query parameter as a JSON object mapping.

    Returns:
        An empty mapping when the parameter is absent or null, otherwise the validated mapping.

    Raises:
        HTTPException: If the parameter is present but not a valid JSON object.
    """
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
    """An authenticated user identity containing the JWT token, expiration, and user record."""

    token: str
    expires: DateTime
    user: User


def create_identity(
    user: User,
    authentication: ServerAuthenticationConfig,
) -> Identity:
    """Create a signed JWT identity for the given user using the server authentication config.

    Args:
        user: The user to issue a token for.
        authentication: Server auth config providing the signing secret and token duration.

    Returns:
        An `Identity` containing the encoded token, its expiration time, and the user.
    """
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
    """Whether the authorization cookie should use secure (HTTPS-only, httponly) settings."""

    INSECURE = "insecure"
    SECURE = "secure"


def assign_authorization_cookie(
    response: Response,
    identity: Identity,
    type: AuthorizationCookieType,
) -> None:
    """Set an `Authorization` cookie on the response with the identity's bearer token.

    Args:
        response: The HTTP response to attach the cookie to.
        identity: The identity whose token and expiration to use.
        type: Whether to set the cookie as secure (HTTPS-only, httponly) or insecure.
    """
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
    """Resolve the current identity from a bearer token in the Authorization header or cookie.

    Return ``None`` when authentication is disabled, no token is provided, the token is invalid,
    or the referenced user no longer exists.
    """
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
            expires = validate(datetime if TYPE_CHECKING else DateTime, expires)
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
    """Return the current identity, raising if the caller is not authenticated.

    Raises:
        NotAuthenticatedError: If no identity is present.
    """
    if identity is None:
        raise NotAuthenticatedError()

    return identity


type RequireIdentity = Annotated[Identity, Depends(_get_required_identity)]


async def _get_current_user(identity: CurrentIdentity) -> User | None:
    """Return the user from the current identity, or ``None`` if not authenticated."""
    if identity is None:
        return None

    return identity.user


type CurrentUser = Annotated[User | None, Depends(_get_current_user)]


async def _require_current_user(user: CurrentUser) -> User:
    """Return the current user, raising HTTP 401 if not authenticated.

    Raises:
        HTTPException: If no user is present.
    """
    if user is None:
        raise HTTPException(HTTP_401_UNAUTHORIZED)

    return user


type RequireUser = Annotated[User, Depends(_require_current_user)]


def _get_current_role(user: CurrentUser, cli: CurrentCLI) -> UserRole | None:
    """Return the effective role of the current caller.

    CLI mode always resolves to admin. Unauthenticated callers resolve to ``None``.
    """
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
    """Enforce a minimum role requirement for the current caller.

    Bypass the check when authentication is disabled or the request comes from the CLI.

    Args:
        required: The minimum `UserRole` needed to proceed.
        engine: The current engine instance (used to check the auth config).
        user: The current user, or ``None`` if unauthenticated.
        cli: Whether the app is in CLI mode.
        role: The effective role of the caller.

    Returns:
        The authenticated user, or ``None`` when access is granted without a user context.

    Raises:
        NotAuthenticatedError: If the caller is unauthenticated.
        NotPermittedError: If the caller is disabled or lacks the required role.
    """
    if engine.config.server.authentication is None:
        # Authentication is disabled, so allow all users.
        return None
    if cli:
        # The CLI is functionally an admin, and so can do anything.
        return None

    if user is None:
        raise NotAuthenticatedError()
    if user.disabled or role < required:
        raise NotPermittedError()

    return user


def _require_viewer(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    """Require at least viewer-level access for the current caller."""
    return _restrict(UserRole.VIEWER, engine, user, cli, role)


def _require_operator(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    """Require at least operator-level access for the current caller."""
    return _restrict(UserRole.OPERATOR, engine, user, cli, role)


def _require_admin(
    engine: CurrentEngine,
    user: CurrentUser,
    cli: CurrentCLI,
    role: CurrentRole,
) -> User | None:
    """Require admin-level access for the current caller."""
    return _restrict(UserRole.ADMIN, engine, user, cli, role)


VIEWER = Depends(_require_viewer)
OPERATOR = Depends(_require_operator)
ADMIN = Depends(_require_admin)

type RequireViewer = Annotated[User | None, VIEWER]
type RequireOperator = Annotated[User | None, OPERATOR]
type RequireAdmin = Annotated[User | None, ADMIN]


def assert_found[T](value: T | None, /) -> T:
    """Return `value` if it is not ``None``, otherwise raise a not-found error.

    Raises:
        NotFoundError: If `value` is ``None``.
    """
    if value is None:
        raise NotFoundError()

    return value


def create_record_get_route(router: Router, Record: type[Record]):
    """Register a GET-by-ID route on `router` for the given record type."""
    naming = Record.__entity_naming__

    async def get(engine: CurrentEngine, id: UUID):
        filter = cast("type[MessageFilter]", Record.Filter)(id=id)
        return assert_found(await engine.__manager__(Record).where(filter).first())

    get.__name__ = f"get_{snakecase(naming.singular)}"
    return router.get(
        "/{id:uuid}",
        response_model=Record,
        dependencies=[VIEWER],
        tags=[kebabcase(naming.plural)],
    )(get)


def create_record_get_all_route(router: Router, Record: type[Record], limit: int):
    """Register a GET-all route on `router` for the given record type with a result limit."""
    naming = Record.__entity_naming__

    async def get_all(
        engine: CurrentEngine,
        filter: Annotated[
            Record.Filter,  # type: ignore
            Query(),
            Limit(limit),
        ],
    ):
        return await engine.__manager__(Record).where(filter)

    get_all.__name__ = f"get_all_{snakecase(naming.plural)}"
    return router.get(
        "",
        response_model=list[Record],
        dependencies=[VIEWER],
        tags=[kebabcase(naming.plural)],
    )(get_all)


def create_record_count_route(router: Router, Record: type[Record]):
    """Register a count route on `router` that return the number of matching records."""
    naming = Record.__entity_naming__

    async def count(
        engine: CurrentEngine,
        filter: Annotated[Record.Filter, Query()],  # type: ignore
    ) -> int:
        return await engine.__manager__(Record).where(filter).count()

    count.__name__ = f"count_{snakecase(naming.plural)}"
    return router.get(
        "/count",
        dependencies=[VIEWER],
        tags=[kebabcase(naming.plural)],
    )(count)


def create_record_stream_route(router: Router, Record: type[Record]):
    """Register a WebSocket streaming route on `router` for the given record type."""
    naming = Record.__entity_naming__

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

    stream.__name__ = f"stream_{snakecase(naming.plural)}"
    return router.websocket("", dependencies=[VIEWER])(stream)


def create_record_router(name: str, Record: type[Record], *, limit: int = 1000):
    """Create a router with standard CRUD and streaming routes for a record type.

    Register get-by-ID, get-all (with limit), count, and WebSocket stream routes under the
    given `name` prefix.

    Args:
        name: The URL prefix and OpenAPI tag for the generated routes.
        Record: The record type to build routes for.
        limit: Maximum number of results for the get-all route.

    Returns:
        A configured `Router` with the standard record routes registered.
    """
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
    """Require that the caller is either the user identified in the URL path or an admin.

    Extract the target user ID from the `user_id` or `id` path parameter and verify the
    caller has permission to act on that user's behalf.

    Raises:
        NotPermittedError: If the path parameter is missing or the caller lacks permission.
    """
    user_id = connection.path_params.get("user_id") or connection.path_params.get("id")
    if user_id is None:
        raise NotPermittedError()

    try:
        user_id = UUID(str(user_id))
    except ValueError:
        raise NotPermittedError()

    if role < UserRole.ADMIN:
        if user is None or user.id != user_id:
            raise NotPermittedError()

    return user_id


SELF_OR_ADMIN = Depends(_require_self_or_admin)


def Limit[FilterT: BaseEntityFilter](max: int) -> AfterValidator:
    """Create a Pydantic `AfterValidator` that caps a filter's `limit` field at `max`.

    If the filter has no limit set, default it to `max`. If the limit exceeds `max`, raise a
    validation error.

    Args:
        max: The maximum allowed value for the filter's `limit` field.

    Returns:
        An `AfterValidator` that enforces the limit constraint.
    """

    def validate_limit(filter: FilterT) -> FilterT:
        if filter.limit is None:
            filter = filter.model_copy(update={"limit": max})
        elif filter.limit > max:
            raise PydanticKnownError("less_than_equal", {"le": max})

        return filter

    return AfterValidator(validate_limit)
