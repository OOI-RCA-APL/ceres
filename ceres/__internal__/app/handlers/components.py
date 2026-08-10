import traceback
from typing import TYPE_CHECKING, Any, Literal

from ceres.__internal__.app.shared import (
    get_component_access,
    get_components_access,
)
from ceres.__internal__.interop import _self_contained
from ceres.__internal__.particles import declared_particle_classes
from ceres.__internal__.utilities.text import strify
from ceres.address import Address
from ceres.component import (
    ActionBinding,
    Component,
    ComponentAccessLevel,
    ProcedureBinding,
    ProcedureType,
    QueryBinding,
)
from ceres.connectivity import Connectivity
from ceres.data import DataModel, DataObject, DateTime, Name, to_json_schema
from ceres.error import (
    NotConnectedError,
    NotFoundError,
    NotPermittedError,
    ProcedureComponentNotFoundError,
    ProcedureNotFoundError,
    ProcedureNotPermittedError,
)
from ceres.message import Message, MessageData
from ceres.particle import Particle, _get_cls_particle_type

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from ceres.__internal__.app.shared import Actor
    from ceres.config import ComponentConfig
    from ceres.engine import Engine


class ConnectionInfo(DataObject):
    """Summary of a named connection on a component."""

    name: Name
    label: str


class ComponentInfo(DataObject):
    """Recursive description of a component, its procedures, connections, and children."""

    name: Name
    address: Address
    procedures: list[ProcedureBinding]
    connections: list[ConnectionInfo]
    components: list[ComponentInfo]
    tags: list[str]


ComponentInfo.__name__ = "Component"
ComponentInfo.__qualname__ = "Component"


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


async def get_components(engine: Engine, actor: Actor) -> list[ComponentInfo]:
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


async def get_component(engine: Engine, actor: Actor, address: Address) -> ComponentInfo:
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


async def _resolve_component(engine: Engine, actor: Actor, address: Address) -> Component:
    """Resolve the component at `address`, checking that `actor` may view it.

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

    return component


async def get_component_config(
    engine: Engine,
    actor: Actor,
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
    component = await _resolve_component(engine, actor, address)
    return component.system.config


class ConnectionStateInfo(DataObject):
    """A component connection together with its current connectivity state."""

    name: Name
    label: str
    connectivity: Connectivity


async def get_component_connections(
    engine: Engine,
    actor: Actor,
    address: Address,
) -> list[ConnectionStateInfo]:
    """Return the component's connections with their live connectivity states.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    component = await _resolve_component(engine, actor, address)
    return [
        ConnectionStateInfo(
            name=connection.name,
            label=connection.label,
            connectivity=connection.connectivity,
        )
        for connection in component.system.connections.all()
        if connection.name is not None
    ]


class JobInfo(DataObject):
    """Description of a scheduled job on a component."""

    name: Name
    action: Name
    schedule: str
    """Human-readable form of the job's schedule."""
    next_run: DateTime | None
    """When the job is next expected to run, or `None` when the scheduler is not running."""


def _describe_schedule(schedule: object) -> str:
    """Render a job schedule in the short form it is written as in configuration."""
    from ceres.schedule import CronSchedule, IntervalSchedule

    if isinstance(schedule, CronSchedule):
        return schedule.crontab

    if isinstance(schedule, IntervalSchedule):
        return strify(schedule.interval)

    return strify(schedule)


async def get_component_jobs(
    engine: Engine,
    actor: Actor,
    address: Address,
) -> list[JobInfo]:
    """Return the scheduled jobs for the component at the given address.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    component = await _resolve_component(engine, actor, address)
    jobs = component.system.jobs
    return [
        JobInfo(
            name=job.name,
            action=job.action,
            schedule=_describe_schedule(job.schedule),
            next_run=jobs.get_next_fire_time(job.name),
        )
        for job in jobs.get_all()
    ]


class ParticleFieldInfo(DataObject):
    """Description of one field on a particle's `data` model."""

    name: str
    schema: dict[str, Any]
    """The field's JSON Schema subtree verbatim, the console derives plottability and captions."""


class ParticleTypeInfo(DataObject):
    """Description of one particle type a component declares."""

    type: str
    description: str | None
    fields: list[ParticleFieldInfo]


def _describe_particle_class(cls: type[Particle]) -> ParticleTypeInfo:
    """Describe one particle class from its `data` model's JSON schema.

    Each field's schema subtree is inlined against the model's `$defs` since it ships on
    its own, detached from the schema that defined those references.
    """
    schema = to_json_schema(cls.Data)
    definitions = schema.get("$defs", {})
    fields = [
        ParticleFieldInfo(name=name, schema=_self_contained(property, definitions, frozenset()))
        for name, property in schema.get("properties", {}).items()
    ]

    discriminator = _get_cls_particle_type(cls)
    if discriminator is None:
        raise ValueError(f"`{cls}` has no `type` discriminator.")

    return ParticleTypeInfo(
        type=discriminator,
        description=cls.__doc__,
        fields=fields,
    )


async def get_component_particle_types(
    engine: Engine,
    actor: Actor,
    address: Address,
) -> list[ParticleTypeInfo]:
    """Return the particle types the component at `address` declares.

    Available to anyone who can access the component at all.

    Raises:
        NotFoundError: If no component matches the given address.
        NotPermittedError: If the caller has no access to the component.
    """
    component = await _resolve_component(engine, actor, address)
    return [_describe_particle_class(cls) for cls in declared_particle_classes(component)]


async def get_procedures(engine: Engine, address: Address) -> list[ProcedureBinding]:
    """Return all procedure bindings for the component at the given address.

    Raises:
        NotFoundError: If no component matches the given address.
    """
    component = engine.get_component(address)
    if component is None:
        raise NotFoundError()

    return list(component.system.get_procedure_bindings().values())


async def get_procedure(
    engine: Engine,
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


async def get_queries(
    engine: Engine,
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


async def get_query_info(
    engine: Engine,
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


async def get_actions(
    engine: Engine,
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


async def get_action(
    engine: Engine,
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


type CallResult = Any
"""What a procedure answered with, a value, a media output, or nothing."""


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


async def call_natively(
    *,
    engine: Engine,
    actor: Actor,
    address: Address,
    procedure: Name,
    namespace: _ProcedureNamespace,
    method: str,
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

    if method == "GET" and binding.type == ProcedureType.ACTION:
        raise ProcedureNotPermittedError()

    # A media output travels as itself, so the caller decides how to serve its body.
    return await component.system.call(procedure, arguments)


_ProcedureNamespace = Literal["procedures", "queries", "actions"]


async def subscribe_natively(
    *,
    engine: Engine,
    actor: Actor,
    address: Address,
    procedure: Name,
    namespace: _ProcedureNamespace,
    arguments: dict[Name, object] | None = None,
) -> AsyncIterator[object]:
    """Subscribe to a procedure, yielding its outputs as they arrive.

    Refusals raise their typed errors, which the caller renders as the socket's close
    code and reason.

    Raises:
        ProcedureComponentNotFoundError: If the component is not found.
        ProcedureNotFoundError: If the procedure is not found or is in another namespace.
        ProcedureNotPermittedError: If the caller lacks permission.
    """
    component = engine.get_component(address)
    if component is None:
        raise ProcedureComponentNotFoundError()

    binding = component.system.get_procedure_bindings().get(procedure)
    if binding is None:
        raise ProcedureNotFoundError()

    if namespace == "queries" and binding.type != ProcedureType.QUERY:
        raise ProcedureNotFoundError()
    if namespace == "actions" and binding.type != ProcedureType.ACTION:
        raise ProcedureNotFoundError()

    await _assert_procedure_access(engine, actor, component, binding)

    async for output in component.system.subscribe(procedure, arguments):
        yield output


class SendMessageInput(DataModel):
    """Request body for sending a message through a component connection."""

    data: MessageData


async def send_message(
    engine: Engine,
    actor: Actor,
    address: Address,
    connection: str,
    input: SendMessageInput,
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
