import warnings
from collections.abc import AsyncIterator, Callable, Coroutine, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, cast, override
from uuid import UUID

import jwt.warnings
from ceres_core import RecordBatch
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
from ceres.user import User

# Allow using short JWT secrets without warnings.
warnings.filterwarnings("ignore", category=jwt.warnings.InsecureKeyLengthWarning, module="jwt")

if TYPE_CHECKING:
    from enum import Enum

    from asgiref.typing import WebSocketReceiveEvent
    from ceres_core import ServerAuthenticationConfig
    from pydantic.main import IncEx

    from ceres.__internal__.app.main import App
    from ceres.__internal__.server import Server
    from ceres.access import ResolvedAccess
    from ceres.address import Address
    from ceres.component import Component, ComponentAccessLevel, ComponentSystem
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

CREDENTIAL_FIELDS = ("secret", "password", "key_password")
"""Credential field names dropped from any serialized configuration.

The signing secret mints a token for any user, so serving it to an administrator hands over every
account. Dropped by name at every nesting level, which also covers a credential named this way
inside a component's own configuration.
"""


def scrub_credentials(value: Any) -> Any:
    """Remove credential fields from a serialized payload at every nesting level.

    Operates on the final JSON-compatible payload rather than through Pydantic's
    include/exclude machinery, so it reaches inside natively-serialized configuration
    sections that Pydantic cannot descend into.

    Args:
        value: A JSON-compatible payload.

    Returns:
        The payload with every credential field removed.
    """
    if isinstance(value, dict):
        return {
            key: scrub_credentials(current)
            for key, current in value.items()
            if key not in CREDENTIAL_FIELDS
        }

    if isinstance(value, list):
        return [scrub_credentials(current) for current in value]

    return value


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
    impersonated_by: UUID | None = None
    """Administrator impersonating this identity, marking it as not their own account.

    A marker for the console to show, not a right. Impersonating is administrators only, and the
    identity it issues is somebody else's, so it confers nothing.
    """


def create_identity(
    user: User,
    authentication: ServerAuthenticationConfig,
    impersonated_by: UUID | None = None,
) -> Identity:
    """Create a signed JWT identity for the given user using the server authentication config.

    Args:
        user: The user to issue a token for.
        authentication: Server auth config providing the signing secret and token duration.
        impersonated_by: Administrator who took on this identity by impersonating, recorded
            so they can return to their own account without their password. `None` for a token
            issued to the user themselves.

    Returns:
        An `Identity` containing the encoded token, its expiration time, and the user.
    """
    import jwt

    expires = utc() + authentication.duration
    claims: dict[str, Any] = {
        "sub": str(user.id),
        "exp": expires,
    }
    if impersonated_by is not None:
        claims["imp"] = str(impersonated_by)

    token = jwt.encode(claims, authentication.secret, "HS256")

    return Identity(
        user=user,
        token=token,
        expires=expires,
        impersonated_by=impersonated_by,
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

        impersonated_by = info.get("swf")
        try:
            impersonated_by = UUID(str(impersonated_by)) if impersonated_by is not None else None
        except ValueError:
            return None

        return Identity(
            token=token,
            expires=expires,
            user=user,
            impersonated_by=impersonated_by,
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


@dataclass(frozen=True, kw_only=True)
class Actor:
    """The acting context of a request: the user plus CLI/auth-disabled bypass state."""

    user: User | None
    unrestricted: bool
    """Whether the request bypasses all permission checks (CLI or auth disabled)."""

    @property
    def admin(self) -> bool:
        """Whether the actor has admin capability."""
        return self.unrestricted or (self.user is not None and self.user.admin)

    @property
    def authenticated(self) -> bool:
        """Whether the actor is an authenticated user or an unrestricted context."""
        return self.unrestricted or self.user is not None


def _get_current_actor(engine: CurrentEngine, user: CurrentUser, cli: CurrentCLI) -> Actor:
    """Return the acting context of the current caller.

    CLI mode and disabled authentication are unrestricted. Otherwise the actor wraps the
    current user, who may be ``None`` when unauthenticated.
    """
    unrestricted = cli or engine.config.server.authentication is None
    return Actor(user=user, unrestricted=unrestricted)


type CurrentActor = Annotated[Actor, Depends(_get_current_actor)]


def _require_authenticated(actor: CurrentActor) -> User | None:
    """Require an authenticated caller.

    Returns:
        The authenticated user, or ``None`` when access is granted without a user context.

    Raises:
        NotAuthenticatedError: If the caller is unauthenticated.
        NotPermittedError: If the caller is disabled.
    """
    if actor.unrestricted:
        return None
    if actor.user is None:
        raise NotAuthenticatedError()
    if actor.user.disabled:
        raise NotPermittedError()

    return actor.user


def _require_admin(actor: CurrentActor) -> User | None:
    """Require an admin caller."""
    user = _require_authenticated(actor)
    if user is not None and not user.admin:
        raise NotPermittedError()

    return user


AUTHENTICATED = Depends(_require_authenticated)
ADMIN = Depends(_require_admin)

type RequireAuthenticated = Annotated[User | None, AUTHENTICATED]
type RequireAdmin = Annotated[User | None, ADMIN]


def assert_found[T](value: T | None, /) -> T:
    """Return `value` if it is not ``None``, otherwise raise a not-found error.

    Raises:
        NotFoundError: If `value` is ``None``.
    """
    if value is None:
        raise NotFoundError()

    return value


async def get_component_access(
    engine: Engine,
    user: User | None,
    component: Component,
) -> ComponentAccessLevel | None:
    """Resolve the effective access level for a user on a component."""
    if user is None:
        return None

    from ceres.access import resolve_access

    system = component.system
    return await resolve_access(
        database=engine.database,
        user=user,
        address_chain=build_address_chain(system),
        resolved_access=system.get_resolved_access(),
        inherited_tags=system.get_inherited_tags(),
    )


async def get_engine_access_detail(engine: Engine, user: User | None) -> ResolvedAccess | None:
    """Resolve a user's access on the engine root, keeping what conferred the level.

    The engine root is the placement that workspaces spanning several components sit on. It has no
    component to resolve against, so it resolves like a component with no address chain and no
    tags, leaving the configured default access and any all-target grant. Authenticated users get
    `VIEW` unless the configuration lowers it, which mirrors how a component with no declared
    access behaves.

    Args:
        engine: Engine whose configuration and grants to resolve against.
        user: The user to check, or `None` for an unauthenticated caller.

    Returns:
        The effective level and its source, or `None` when there is no user or no access.
    """
    from ceres.access import fetch_access_grants, resolve_access_detail_from
    from ceres.component import ComponentAccessLevel

    if user is None:
        return None

    default = (
        engine.default_access if engine.default_access is not None else ComponentAccessLevel.VIEW
    )
    grants = await fetch_access_grants(engine.database, user)
    return resolve_access_detail_from(
        grants,
        address_chain=[],
        resolved_access=default,
        inherited_tags=set(),
    )


async def get_engine_access(engine: Engine, user: User | None) -> ComponentAccessLevel | None:
    """Resolve the effective access level for a user on the engine root.

    Args:
        engine: Engine whose configuration and grants to resolve against.
        user: The user to check, or `None` for an unauthenticated caller.

    Returns:
        The effective `ComponentAccessLevel`, or `None` when there is no user or no access.
    """
    resolved = await get_engine_access_detail(engine, user)
    return resolved.level if resolved is not None else None


async def get_components_access_detail(
    engine: Engine,
    user: User | None,
    components: Iterable[Component],
) -> dict[Address, ResolvedAccess | None]:
    """Resolve access across many components, keeping what conferred each level.

    Args:
        engine: The engine whose database holds the grants.
        user: The user to check, or `None` for an unauthenticated caller with no access.
        components: The components to resolve access for.

    Returns:
        A mapping from each component's address to its resolved level and source, or `None` where
        the user has no access.
    """
    if user is None:
        return {component.system.address: None for component in components}

    from ceres.access import fetch_access_grants, resolve_access_detail_from

    grants = await fetch_access_grants(engine.database, user)

    result: dict[Address, ResolvedAccess | None] = {}
    for component in components:
        system = component.system
        result[system.address] = resolve_access_detail_from(
            grants,
            address_chain=build_address_chain(system),
            resolved_access=system.get_resolved_access(),
            inherited_tags=system.get_inherited_tags(),
        )

    return result


async def get_components_access(
    engine: Engine,
    user: User | None,
    components: Iterable[Component],
) -> dict[Address, ComponentAccessLevel | None]:
    """Resolve the effective access level for a user across many components in one grant fetch.

    Fetch the user's grants once, then resolve each component in memory. Prefer this over calling
    `get_component_access` in a loop, which re-queries the grants for every component.

    Args:
        engine: The engine whose database holds the grants.
        user: The user to check, or `None` for an unauthenticated caller with no access.
        components: The components to resolve access for.

    Returns:
        A mapping from each component's address to its effective level, or `None` where the user
        has no access.
    """
    if user is None:
        return {component.system.address: None for component in components}

    from ceres.access import fetch_access_grants, resolve_access_from

    grants = await fetch_access_grants(engine.database, user)

    result: dict[Address, ComponentAccessLevel | None] = {}
    for component in components:
        system = component.system
        result[system.address] = resolve_access_from(
            grants,
            address_chain=build_address_chain(system),
            resolved_access=system.get_resolved_access(),
            inherited_tags=system.get_inherited_tags(),
        )

    return result


def build_address_chain(system: ComponentSystem) -> list[str]:
    """Build the list of addresses from a component up to its top-level ancestor."""
    chain: list[str] = []
    current: ComponentSystem | None = system
    while current is not None:
        chain.append(str(current.address))
        current = current.parent

    return chain


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
        dependencies=[AUTHENTICATED],
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
        query = engine.__manager__(Record).where(filter)
        if query._get_transform() is not None:
            # A transform (a typed particle class, say) needs Python objects, so the query
            # takes the materializing path.
            return await query

        # Rows parse into native records and serialize in one call, no Python entity
        # objects are built for a plain listing.
        batch = RecordBatch.parse(naming.table, await query.mappings())
        return Response(batch.to_json(), media_type="application/json")

    get_all.__name__ = f"get_all_{snakecase(naming.plural)}"
    return router.get(
        "",
        response_model=list[Record],
        dependencies=[AUTHENTICATED],
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
        dependencies=[AUTHENTICATED],
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
    return router.websocket("", dependencies=[AUTHENTICATED])(stream)


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
    user: RequireAuthenticated,
    actor: CurrentActor,
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

    if not actor.admin:
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
