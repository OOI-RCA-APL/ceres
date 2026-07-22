import traceback
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import Body, Request, Response, WebSocket, WebSocketException
from starlette.status import WS_1008_POLICY_VIOLATION, WS_1011_INTERNAL_ERROR

from ceres.__internal__.app.shared import (
    AUTHENTICATED,
    CurrentActor,
    CurrentEngine,
    CurrentProcedureQueryArguments,
    CurrentSocket,
    CurrentUser,
    Router,
    get_component_access,
    get_components_access,
)
from ceres.__internal__.utilities.text import strify
from ceres.address import Address
from ceres.component import (
    ActionBinding,
    Component,
    ComponentAccessLevel,
    Output,
    ProcedureBinding,
    ProcedureType,
    QueryBinding,
)
from ceres.config import ComponentConfig
from ceres.data import DataModel, DataObject, Name, StrEnum, to_json
from ceres.error import (
    NotConnectedError,
    NotFoundError,
    NotPermittedError,
    ProcedureComponentNotFoundError,
    ProcedureError,
    ProcedureInternalError,
    ProcedureNotFoundError,
    ProcedureNotPermittedError,
)
from ceres.message import Message, MessageData

if TYPE_CHECKING:
    from starlette.requests import HTTPConnection

    from ceres.__internal__.app.shared import Actor
    from ceres.engine import Engine


class ComponentRole(StrEnum):
    """Role a component can fulfill in the system."""

    INTERFACE = "interface"


class ConnectionInfo(DataObject):
    """Summary of a named connection on a component."""

    name: Name
    label: str


class ComponentInfo(DataObject):
    """Recursive description of a component, its roles, procedures, connections, and children."""

    name: Name
    address: Address
    roles: list[ComponentRole]
    procedures: list[ProcedureBinding]
    connections: list[ConnectionInfo]
    components: list[ComponentInfo]
    tags: list[str]


ComponentInfo.__name__ = "Component"
ComponentInfo.__qualname__ = "Component"

router = Router(prefix="/components", tags=["components"])


def _get_component_roles(component: Component | type[Component]) -> list[ComponentRole]:
    """Determine the roles that a component fulfills (e.g. interface).

    Args:
        component: A component instance or class to inspect.

    Returns:
        A list of `ComponentRole` values applicable to the component.
    """
    if not isinstance(component, type):
        component = type(component)

    from ceres.interface import Interface

    roles: list[ComponentRole] = []
    if issubclass(component, Interface):
        roles.append(ComponentRole.INTERFACE)

    return roles


def _describe_component(component: Component, *, visible: bool) -> ComponentInfo:
    """Build a `ComponentInfo` for `component`, its own details omitted when `visible` is `False`.

    A component the caller cannot view is still returned as a bare container so the tree stays
    connected to any visible descendant, but its procedures, connections, and tags are withheld.
    """
    system = component.system
    if visible:
        procedures = list(system.get_procedure_bindings().values())
        connections = [
            ConnectionInfo(name=connection.name, label=connection.label)
            for connection in system.connections.all()
            if connection.name is not None
        ]
        tags = system.tags
    else:
        procedures = []
        connections = []
        tags = []

    return ComponentInfo(
        name=system.name,
        address=system.address,
        roles=_get_component_roles(component),
        procedures=procedures,
        connections=connections,
        components=[],
        tags=tags,
    )


def _build_tree(
    component: Component,
    access: dict[Address, ComponentAccessLevel | None] | None,
) -> ComponentInfo | None:
    """Recursively describe `component` and its children, pruned to what the caller may view.

    When `access` is `None` the caller is unrestricted and the whole subtree is described. Otherwise
    a subtree is kept only if the component or one of its descendants is viewable, and non-viewable
    ancestors are returned as bare containers.

    Returns:
        The described component, or `None` if neither it nor any descendant is viewable.
    """
    children: list[ComponentInfo] = []
    for child in component.system.children:
        described = _build_tree(child.component, access)
        if described is not None:
            children.append(described)

    visible = access is None or access.get(component.system.address) is not None
    if not visible and not children:
        return None

    info = _describe_component(component, visible=visible)
    info.components = children
    return info


@router.get("", dependencies=[AUTHENTICATED])
async def get_components(engine: CurrentEngine, actor: CurrentActor) -> list[ComponentInfo]:
    """Return every top-level component the caller may view as a recursive description."""
    components = engine.get_components()
    if actor.unrestricted:
        access = None
    else:
        access = await get_components_access(engine, actor.user, components)

    result: list[ComponentInfo] = []
    for component in components:
        if component.system.parent is not None:
            continue

        described = _build_tree(component, access)
        if described is not None:
            result.append(described)

    return result


@router.get("/{address}", dependencies=[AUTHENTICATED])
async def get_component(
    engine: CurrentEngine, actor: CurrentActor, address: Address
) -> ComponentInfo:
    """Return a recursive description of a component and all its children the caller may view.

    Raises:
        NotFoundError: If no component matches the given address or the caller cannot view it or
            any of its descendants.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    if actor.unrestricted:
        access = None
    else:
        access = await get_components_access(
            engine, actor.user, component.system.get_components(inclusive=True)
        )

    try:
        info = _build_tree(component, access)
    except Exception:
        traceback.print_exc()
        raise

    if info is None:
        raise NotFoundError()

    return info


@router.get(
    "/{address}/config",
    dependencies=[AUTHENTICATED],
    response_model_exclude_defaults=True,
)
async def get_component_config(
    engine: CurrentEngine,
    actor: CurrentActor,
    address: Address,
) -> ComponentConfig | None:
    """Return the configuration for the component at the given address.

    Fields left at their defaults are omitted so the result reads like the source YAML rather
    than a fully expanded model.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    access = await get_component_access(engine, actor.user, component)
    if not actor.unrestricted and access is None:
        raise NotPermittedError()

    return component.system.config


@router.get("/{address}/procedures", tags=["procedures"])
async def get_procedures(engine: CurrentEngine, address: Address) -> list[ProcedureBinding]:
    """Return all procedure bindings for the component at the given address.

    Raises:
        NotFoundError: If no component matches the given address.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    return list(component.system.get_procedure_bindings().values())


@router.get("/{address}/procedures/{procedure}", tags=["procedures"])
async def get_procedure(
    engine: CurrentEngine,
    address: Address,
    procedure: Name,
) -> ProcedureBinding:
    """Return a single procedure binding by component address and procedure name.

    Raises:
        NotFoundError: If the component or procedure does not exist.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()
    binding = component.system.get_procedure_bindings().get(procedure)
    if binding is None:
        raise NotFoundError()

    return binding


@router.get("/{address}/queries", tags=["queries"])
async def get_queries(
    engine: CurrentEngine,
    address: Address,
) -> list[QueryBinding]:
    """Return all query bindings for the component at the given address.

    Raises:
        NotFoundError: If no component matches the given address.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    return list(component.system.get_query_bindings().values())


@router.get("/{address}/queries/{query}", tags=["queries"])
async def get_query_info(
    engine: CurrentEngine,
    address: Address,
    query: Name,
) -> QueryBinding:
    """Return a single query binding by component address and query name.

    Raises:
        NotFoundError: If the component or query does not exist.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()
    binding = component.system.get_query_bindings().get(query)
    if binding is None:
        raise NotFoundError()

    return binding


@router.get("/{address}/actions", tags=["actions"])
async def get_actions(
    engine: CurrentEngine,
    address: Address,
) -> list[ActionBinding]:
    """Return all action bindings for the component at the given address.

    Raises:
        NotFoundError: If no component matches the given address.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    return list(component.system.get_action_bindings().values())


@router.get("/{address}/actions/{action}", tags=["actions"])
async def get_action(
    engine: CurrentEngine,
    address: Address,
    action: Name,
) -> ActionBinding:
    """Return a single action binding by component address and action name.

    Raises:
        NotFoundError: If the component or action does not exist.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()
    binding = component.system.get_action_bindings().get(action)
    if binding is None:
        raise NotFoundError()

    return binding


if TYPE_CHECKING:
    type CallResult = Any | Response | None
else:
    type CallResult = Any


async def _assert_procedure_access(
    engine: Engine,
    actor: Actor,
    component: Component,
    binding: ProcedureBinding,
) -> None:
    """Check that `actor` may invoke `binding` on `component`.

    Public procedures are open to everyone. Every other procedure requires an authenticated
    caller whose effective access level on the component meets the binding's minimum, with
    unrestricted actors bypassing the level check.

    Raises:
        ProcedureNotPermittedError: If the caller lacks the required access level.
    """
    if binding.permissions == "public":
        return

    if not actor.authenticated:
        raise ProcedureNotPermittedError()

    access = await get_component_access(engine, actor.user, component)
    if not actor.unrestricted and (access is None or access < binding.permissions):
        raise ProcedureNotPermittedError()


async def _call(
    *,
    request: Request,
    engine: CurrentEngine,
    user: CurrentUser,
    actor: CurrentActor,
    address: Address,
    procedure: Name,
    arguments: dict[Name, object] | None = None,
) -> CallResult:
    """Execute a procedure on a component and return the result.

    Validate that the component and procedure exist, that the caller has sufficient component-level
    permission, and that GET requests are not used to invoke actions.

    Raises:
        ProcedureComponentNotFoundError: If the component is not found.
        ProcedureNotFoundError: If the procedure is not found.
        ProcedureNotPermittedError: If the caller lacks permission.
    """
    namespace = _get_namespace(request)

    component = engine.get_component(address)
    if component is None:
        raise ProcedureComponentNotFoundError()

    binding = component.system.get_procedure_bindings().get(procedure)
    if binding is None:
        raise ProcedureNotFoundError()

    if namespace == "queries":
        if binding.type != ProcedureType.QUERY:
            raise ProcedureNotFoundError()

    if namespace == "actions":
        if binding.type != ProcedureType.ACTION:
            raise ProcedureNotFoundError()

    await _assert_procedure_access(engine, actor, component, binding)

    if request.method == "GET" and binding.type == ProcedureType.ACTION:
        raise ProcedureNotPermittedError()

    output = await component.system.call(procedure, arguments)
    if isinstance(output, Output):
        return output.to_response()

    return output


_ProcedureNamespace = Literal["procedures", "queries", "actions"]


def _get_namespace(request: HTTPConnection) -> _ProcedureNamespace:
    """Extract the procedure namespace (procedures, queries, or actions) from the request URL path.

    Raises:
        ValueError: If the URL does not contain a recognized namespace segment.
    """
    if "/procedures" in request.url.path:
        return "procedures"
    elif "/queries" in request.url.path:
        return "queries"
    elif "/actions" in request.url.path:
        return "actions"

    raise ValueError("Invalid namespace.")


async def call_procedure(
    request: Request,
    engine: CurrentEngine,
    user: CurrentUser,
    actor: CurrentActor,
    address: Address,
    name: Name,
    arguments: Annotated[dict[Name, object] | None, Body()] = None,
) -> CallResult:
    """Call a procedure by POST with arguments supplied in the request body."""
    return await _call(
        request=request,
        engine=engine,
        user=user,
        actor=actor,
        address=address,
        procedure=name,
        arguments=arguments,
    )


for namespace, kind in (("procedures", "procedure"), ("queries", "query"), ("actions", "action")):
    name = f"call_{kind}"
    router.post(
        "/{address}/" + namespace + "/{name}/call",
        tags=[namespace],
        name=name,
        operation_id=name,
    )(call_procedure)


async def call_procedure_by_get(
    request: Request,
    engine: CurrentEngine,
    user: CurrentUser,
    actor: CurrentActor,
    address: Address,
    name: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> CallResult:
    """Call a procedure by GET with arguments merged from the `arguments` query parameter and any
    additional query parameters.
    """
    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(request.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    return await _call(
        request=request,
        engine=engine,
        user=user,
        actor=actor,
        address=address,
        procedure=name,
        arguments=arguments,
    )


for namespace, kind in (("procedures", "procedure"), ("queries", "query")):
    name = f"call_{kind}"
    router.get(
        "/{address}/" + namespace + "/{name}/call",
        name=name,
        operation_id=name,
    )(call_procedure)


async def subscribe_procedure(
    socket: CurrentSocket,
    connection: WebSocket,
    engine: CurrentEngine,
    actor: CurrentActor,
    address: Address,
    name: Name,
    query_arguments: CurrentProcedureQueryArguments,
) -> None:
    """Subscribe to a procedure over WebSocket, streaming outputs to the client as they arrive.

    Close the socket with an appropriate code if the procedure raises an error or the caller
    lacks permission.
    """
    namespace = _get_namespace(connection)

    arguments = {}
    arguments.update(query_arguments or {})
    arguments.update(connection.query_params)
    arguments.pop("arguments", None)
    arguments.pop("args", None)

    component = engine.get_component(address)
    if component is None:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            to_json(ProcedureComponentNotFoundError()),
        )

    binding = component.system.get_procedure_bindings().get(name)
    if binding is None:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            to_json(ProcedureNotFoundError()),
        )

    if namespace == "queries":
        if binding.type != ProcedureType.QUERY:
            raise WebSocketException(
                WS_1008_POLICY_VIOLATION,
                to_json(ProcedureNotFoundError()),
            )
    if namespace == "actions":
        if binding.type != ProcedureType.ACTION:
            raise WebSocketException(
                WS_1008_POLICY_VIOLATION,
                to_json(ProcedureNotFoundError()),
            )

    try:
        await _assert_procedure_access(engine, actor, component, binding)
    except ProcedureNotPermittedError as error:
        raise WebSocketException(
            WS_1008_POLICY_VIOLATION,
            to_json(error),
        )

    async def write() -> None:
        try:
            async for output in component.system.subscribe(name, arguments):
                await socket.send(output)
        except Exception as exception:
            if isinstance(exception, ProcedureError):
                if not isinstance(exception, ProcedureInternalError):
                    code = WS_1011_INTERNAL_ERROR
                else:
                    code = WS_1008_POLICY_VIOLATION

                reason = to_json(exception)
            else:
                code = WS_1011_INTERNAL_ERROR
                reason = to_json(strify(exception)[0:100])

            await socket.close(code, reason)

    await socket.execute(write)


for namespace, kind in (("procedures", "procedure"), ("queries", "query")):
    router.websocket("/{address}/" + namespace + "/{name}/subscribe")(subscribe_procedure)


class SendMessageInput(DataModel):
    """Request body for sending a message through a component connection."""

    data: MessageData


@router.post("/{address}/connections/{connection}/send", dependencies=[AUTHENTICATED])
async def send_message(
    engine: CurrentEngine,
    actor: CurrentActor,
    address: Address,
    connection: str,
    input: Annotated[SendMessageInput, Body()],
) -> Message:
    """Send a message through a named connection on the specified component.

    Raises:
        NotFoundError: If the component or connection is not found.
        NotConnectedError: If the connection has no active link.
        NotPermittedError: If the caller lacks operate access on the component.
    """
    from ceres.connection import ConnectionInactive

    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    access = await get_component_access(engine, actor.user, component)
    if not actor.unrestricted and (access is None or access < ComponentAccessLevel.OPERATE):
        raise NotPermittedError()

    target = component.system.connections.get(connection)
    if target is None:
        raise NotFoundError()

    try:
        return await target.send(input.data)
    except ConnectionInactive:
        raise NotConnectedError()
