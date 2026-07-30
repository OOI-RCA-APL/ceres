"""The engine operations the native server dispatches to.

Every operation is a thin adapter over the engine and query layer, validating its
arguments through the same Pydantic models the API always used, so filters, permissions,
redaction, and wire shapes are unchanged by the transport moving to Rust. Arguments
arrive as `{"actor", "path", "query", "body"}`, and results leave either as
JSON-compatible values or as `Raw` text the server serves verbatim.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, Any, cast
from uuid import UUID

from ceres_core import RecordBatch

from ceres.__internal__.app.handlers import components as component_handlers
from ceres.__internal__.app.handlers import engine as engine_handlers
from ceres.__internal__.app.handlers import permissions as permission_handlers
from ceres.__internal__.app.handlers import settings as setting_handlers
from ceres.__internal__.app.handlers import workspace_edits as edit_handlers
from ceres.__internal__.app.handlers import workspaces as workspace_handlers
from ceres.__internal__.app.host import Host, Raw, operation, stream
from ceres.__internal__.app.shared import RECORD_TABLES, Actor, Limit, exclude_recursively
from ceres.address import Address
from ceres.alert import Alert
from ceres.component import BaseOutput, ComponentFilter
from ceres.data import Name, to_json, validate
from ceres.error import (
    HTTPError,
    NotAuthenticatedError,
    NotFoundError,
    NotPermittedError,
    simplify,
)
from ceres.group import Group, GroupFilter, GroupMembership
from ceres.logs import LogEntry, get_logger
from ceres.message import Message
from ceres.particle import Particle
from ceres.setting import Setting
from ceres.statistics import StatisticsFilter
from ceres.user import User, UserFilter
from ceres.workspace import Workspace, WorkspaceEditFilter, WorkspaceFilter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

EXCLUDE_PASSWORDS = exclude_recursively(["password"])
"""Passwords never leave, at any nesting level."""

RECORDS: Mapping[str, tuple[type[Any], int]] = {
    "messages": (Message, 1000),
    "particles": (Particle, 5000),
    "alerts": (Alert, 1000),
    "logs": (LogEntry, 1000),
}
"""Each record table's entity type and listing limit."""


def _pairs(arguments: dict[str, Any]) -> dict[str, Any]:
    """Fold ordered query pairs into a mapping, repeats collecting into lists."""
    data: dict[str, Any] = {}
    for name, value in arguments.get("query") or ():
        if name not in data:
            data[name] = value
        elif isinstance(data[name], list):
            data[name].append(value)
        else:
            data[name] = [data[name], value]

    return data


def _filter[T](model: type[T], arguments: dict[str, Any], limit: int | None = None) -> T:
    """Validate a filter from the request's query pairs."""
    if limit is not None:
        return validate(Annotated[model, Limit(limit)], _pairs(arguments))

    return validate(model, _pairs(arguments))


def _path(arguments: dict[str, Any], name: str) -> str:
    """Read one path parameter, which the server guaranteed is present."""
    return str((arguments.get("path") or {})[name])


def _uuid(arguments: dict[str, Any], name: str) -> UUID:
    """Read one path parameter as a UUID, reporting a malformed one as a bad request.

    Most routes declare their captures as UUIDs and never match a malformed one, so this
    matters where a route takes the capture as text, which is where the framework's own
    coercion reported a validation failure rather than a missing route.
    """
    return validate(UUID, _path(arguments, name))


def _address(arguments: dict[str, Any], name: str = "address") -> Address:
    return validate(Address, _path(arguments, name))


def _body(arguments: dict[str, Any]) -> Any:
    return arguments.get("body")


def _validated[T](model: type[T], arguments: dict[str, Any]) -> T:
    """Validate a request body against its model."""
    return validate(model, _body(arguments) or {})


async def _actor(host: Host, arguments: dict[str, Any]) -> Actor:
    """Rebuild the actor the server resolved, its user fetched when it names one."""
    described = arguments.get("actor") or {}
    identifier = described.get("user")
    user = None
    if identifier is not None:
        user = await host.engine.users.get(UUID(str(identifier)))

    return Actor(user=user, unrestricted=bool(described.get("unrestricted")))


async def _require_user(host: Host, arguments: dict[str, Any]) -> Any:
    """Return the user behind the actor, `None` when the context grants access without one.

    An unrestricted context, the CLI or a server with authentication disabled, has no user
    and passes through, which is what the routes have always been handed.

    Raises:
        NotAuthenticatedError: If there is no user and nothing granting access without one.
        NotPermittedError: If the user is disabled.
    """
    actor = await _actor(host, arguments)
    if actor.unrestricted:
        return None

    if actor.user is None:
        raise NotAuthenticatedError()

    if actor.user.disabled:
        raise NotPermittedError()

    return actor.user


def _serialize(value: Any, exclude: Any = None) -> Raw:
    """Serialize a value once, for the server to splice into its response verbatim."""
    return Raw(to_json(value, exclude=exclude))


def _entities(values: Sequence[Any], exclude: Any = None) -> Raw:
    """Serialize a listing once, one serializer pass per entity and no parse back."""
    return Raw("[" + ",".join(to_json(value, exclude=exclude) for value in values) + "]")


@operation("config")
async def config(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(host.engine.config)


@operation("config.service")
async def config_service(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(host.engine.config.service)


@operation("config.server")
async def config_server(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(host.engine.config.server)


@operation("config.database")
async def config_database(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(host.engine.config.database)


@operation("config.console")
async def config_console(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(host.engine.config.console)


def _record_type(arguments: dict[str, Any]) -> tuple[type[Any], int]:
    table = str(arguments["table"])
    if table not in RECORDS:
        raise NotFoundError()

    return RECORDS[table]


@operation("records.list")
async def records_list(host: Host, arguments: dict[str, Any]) -> Any:
    """Serve a record listing, natively wherever the query allows it."""
    Record, limit = _record_type(arguments)
    filter = _filter(Record.Filter, arguments, limit)
    query = host.engine.__manager__(Record).where(filter)
    table = RECORD_TABLES[Record.__entity_naming__.table]

    # A transform (a typed particle class, say) needs Python objects, so the query takes
    # the materializing path.
    if query._get_transform() is not None:
        return _entities(await query)

    batch = None
    fetcher = query._get_database()._record_fetcher()
    if fetcher is not None:
        # The query compiles here and executes natively, rows never enter Python at all,
        # and any filter the query layer can express is covered.
        sql, parameters = await query.compiled()
        try:
            batch = await fetcher.fetch_sql(table, sql, parameters)
        except (TypeError, ValueError) as error:
            # The native engine can lag the Python one in corner cases. The listing stays
            # correct through the fallback, just slower.
            get_logger("ceres.database").warning(
                f"Native record fetch fell back to the query layer. {error}"
            )

    if batch is None:
        batch = RecordBatch.parse(table, await query.mappings())

    return Raw(batch.to_json().decode())


@operation("records.count")
async def records_count(host: Host, arguments: dict[str, Any]) -> Any:
    Record, _ = _record_type(arguments)
    filter = _filter(Record.Filter, arguments)
    return await host.engine.__manager__(Record).where(filter).count()


@operation("records.get")
async def records_get(host: Host, arguments: dict[str, Any]) -> Any:
    Record, _ = _record_type(arguments)
    filter = Record.Filter(id=UUID(str(arguments["id"])))
    record = await host.engine.__manager__(Record).where(filter).first()
    if record is None:
        raise NotFoundError()

    return _serialize(record)


@stream("records.stream")
async def records_stream(host: Host, arguments: dict[str, Any]) -> AsyncIterator[str]:
    """Stream live records, serializing natively where the wire format allows."""
    Record, _ = _record_type(arguments)
    filter = _filter(Record.Filter, arguments)
    table = RECORD_TABLES[Record.__entity_naming__.table]

    manager = cast("Any", host.engine.__manager__(Record))
    async for record in manager.stream.where(filter):
        if type(record) is Record:
            try:
                yield RecordBatch.record_to_json(table, record).decode()
                continue
            except ValueError:
                pass

        yield to_json(record)


def _control(name: str):
    """Register one of the engine's component control operations."""
    handler = getattr(engine_handlers, name)

    @operation(f"engine.{name}")
    async def control(host: Host, arguments: dict[str, Any]) -> Any:
        filter = _validated(ComponentFilter, arguments)
        actor = await _actor(host, arguments)
        return _serialize(await handler(engine=host.engine, actor=actor, filter=filter))

    return control


for _name in ("start", "stop", "enable", "disable", "up", "down"):
    _control(_name)


@operation("engine.reload")
async def engine_reload(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(await host.engine.reload())


@operation("users.list")
async def users_list(host: Host, arguments: dict[str, Any]) -> Any:
    filter = _filter(UserFilter, arguments, 1000)
    return _entities(await host.engine.users.where(filter), EXCLUDE_PASSWORDS)


@operation("users.count")
async def users_count(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.users.where(_filter(UserFilter, arguments)).count()


@operation("users.get")
async def users_get(host: Host, arguments: dict[str, Any]) -> Any:
    user = await host.engine.users.get(_uuid(arguments, "id"))
    if user is None:
        raise NotFoundError()

    return _serialize(user, EXCLUDE_PASSWORDS)


@operation("users.create")
async def users_create(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(User.Create, arguments)
    return _serialize(await host.engine.users.create(data), EXCLUDE_PASSWORDS)


@operation("users.update")
async def users_update(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    data = _validated(User.Update, arguments)

    # Only administrators may change another account's standing.
    if not actor.admin and ("admin" in data or "disabled" in data):
        raise NotPermittedError()

    updated = await host.engine.users.where(id=_uuid(arguments, "id")).update(data).first()
    if updated is None:
        raise NotFoundError()

    return _serialize(updated, EXCLUDE_PASSWORDS)


@operation("users.delete")
async def users_delete(host: Host, arguments: dict[str, Any]) -> Any:
    user = await host.engine.users.get(_uuid(arguments, "id"))
    if user is None:
        raise NotFoundError()

    await host.engine.users.where(id=user.id).delete()
    return _serialize(user, EXCLUDE_PASSWORDS)


@operation("statistics.list")
async def statistics_list(host: Host, arguments: dict[str, Any]) -> Any:
    filter = _filter(StatisticsFilter, arguments)
    return _entities(await host.engine.statistics.get_all(filter))


@operation("statuses.list")
async def statuses_list(host: Host, arguments: dict[str, Any]) -> Any:
    filter = _filter(ComponentFilter, arguments)
    return _entities(await host.engine.get_statuses(filter))


@operation("statuses.get")
async def statuses_get(host: Host, arguments: dict[str, Any]) -> Any:
    component = host.engine.get_node(_address(arguments))
    if component is None:
        raise NotFoundError()

    return _serialize(await component.get_status())


@stream("statuses.stream")
async def statuses_stream(host: Host, arguments: dict[str, Any]) -> AsyncIterator[str]:
    filter = _filter(ComponentFilter, arguments)
    async for statuses in host.engine.stream_statuses(filter):
        yield to_json(statuses)


@operation("components.list")
async def components_list(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    return _entities(await component_handlers.get_components(engine=host.engine, actor=actor))


@operation("components.get")
async def components_get(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    described = await component_handlers.get_component(
        engine=host.engine, actor=actor, address=_address(arguments)
    )
    return _serialize(described)


@operation("components.config")
async def components_config(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    config = await component_handlers.get_component_config(
        engine=host.engine, actor=actor, address=_address(arguments)
    )
    return None if config is None else Raw(to_json(config, exclude_defaults=True))


@operation("components.connections")
async def components_connections(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    return _entities(
        await component_handlers.get_component_connections(
            engine=host.engine, actor=actor, address=_address(arguments)
        )
    )


@operation("components.jobs")
async def components_jobs(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    return _entities(
        await component_handlers.get_component_jobs(
            engine=host.engine, actor=actor, address=_address(arguments)
        )
    )


@operation("components.send")
async def components_send(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    data = _validated(component_handlers.SendMessageInput, arguments)
    sent = await component_handlers.send_message(
        engine=host.engine,
        actor=actor,
        address=_address(arguments),
        connection=validate(Name, _path(arguments, "connection")),
        input=data,
    )
    return _serialize(sent)


def _bindings(namespace: str):
    """Register the listing and single-binding operations for one namespace."""
    getters = {
        "procedures": "get_procedure_bindings",
        "queries": "get_query_bindings",
        "actions": "get_action_bindings",
    }

    def component_of(host: Host, arguments: dict[str, Any]):
        component = host.engine.get_component(_address(arguments))
        if component is None:
            raise NotFoundError()

        return component

    @operation(f"{namespace}.list")
    async def listing(host: Host, arguments: dict[str, Any]) -> Any:
        component = component_of(host, arguments)
        bindings = getattr(component.system, getters[namespace])()
        return _entities(list(bindings.values()))

    @operation(f"{namespace}.get")
    async def single(host: Host, arguments: dict[str, Any]) -> Any:
        component = component_of(host, arguments)
        bindings = getattr(component.system, getters[namespace])()
        binding = bindings.get(validate(Name, _path(arguments, "name")))
        if binding is None:
            raise NotFoundError()

        return _serialize(binding)

    return listing, single


for _namespace in ("procedures", "queries", "actions"):
    _bindings(_namespace)


def _called_with(arguments: dict[str, Any]) -> dict[str, Any]:
    """The arguments a call by query supplies, from `arguments` and the plain parameters.

    The `arguments` parameter carries a JSON object, and the plain parameters sit over it,
    a repeat taking its last value. Both `arguments` and `args` drop out afterwards, so
    neither reaches the procedure as an argument of its own.

    Raises:
        HTTPError: If `arguments` is present and is not a JSON object.
    """
    supplied: dict[str, Any] = {}
    plain: dict[str, Any] = {}
    for name, value in arguments.get("query") or ():
        if name == "arguments" and value not in ("", "null"):
            try:
                decoded = json.loads(value)
            except ValueError:
                decoded = None

            if not isinstance(decoded, Mapping):
                raise HTTPError(status=400)

            supplied.update(cast("Mapping[str, Any]", decoded))

        plain[name] = value

    supplied.update(plain)
    supplied.pop("arguments", None)
    supplied.pop("args", None)
    return supplied


def _calls(namespace: str):
    """Register the call operations for one namespace, by body and by query."""

    async def call(host: Host, arguments: dict[str, Any], method: str) -> Any:
        actor = await _actor(host, arguments)
        if method == "GET":
            supplied = _called_with(arguments)
        else:
            supplied = _body(arguments)

        result = await component_handlers.call_natively(
            engine=host.engine,
            actor=actor,
            address=_address(arguments),
            procedure=validate(Name, _path(arguments, "name")),
            arguments=supplied,
            namespace=cast("Any", namespace),
            method=method,
        )

        # A procedure declaring media answers with an output the server serves as a body
        # of its own, described rather than serialized into the payload.
        if isinstance(result, BaseOutput):
            return host.serve(result)

        return _serialize(result)

    @operation(f"{namespace}.call")
    async def by_body(host: Host, arguments: dict[str, Any]) -> Any:
        return await call(host, arguments, "POST")

    @operation(f"{namespace}.call_get")
    async def by_query(host: Host, arguments: dict[str, Any]) -> Any:
        return await call(host, arguments, "GET")

    @stream(f"{namespace}.subscribe")
    async def subscription(host: Host, arguments: dict[str, Any]) -> AsyncIterator[str]:
        actor = await _actor(host, arguments)
        async for output in component_handlers.subscribe_natively(
            engine=host.engine,
            actor=actor,
            address=_address(arguments),
            procedure=validate(Name, _path(arguments, "name")),
            arguments=_called_with(arguments),
            namespace=cast("Any", namespace),
        ):
            yield to_json(output)

    return by_body, by_query, subscription


for _namespace in ("procedures", "queries", "actions"):
    _calls(_namespace)


async def _require_group(host: Host, id: UUID) -> None:
    """Refuse when no group carries an ID, which the membership routes check first.

    Raises:
        NotFoundError: If no group has that ID.
    """
    if await host.engine.database.groups.get(id) is None:
        raise NotFoundError()


@operation("groups.list")
async def groups_list(host: Host, arguments: dict[str, Any]) -> Any:
    return _entities(await host.engine.database.groups.where(_filter(GroupFilter, arguments)))


@operation("groups.count")
async def groups_count(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.database.groups.where(_filter(GroupFilter, arguments)).count()


@operation("groups.get")
async def groups_get(host: Host, arguments: dict[str, Any]) -> Any:
    found = await host.engine.database.groups.get(_uuid(arguments, "id"))
    if found is None:
        raise NotFoundError()

    return _serialize(found)


@operation("groups.create")
async def groups_create(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(Group.Create, arguments)
    return _serialize(await host.engine.database.groups.create(data))


@operation("groups.update")
async def groups_update(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(Group.Update, arguments)
    return await host.engine.database.groups.where(id=_uuid(arguments, "id")).update(data)


@operation("groups.delete")
async def groups_delete(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.database.groups.where(id=_uuid(arguments, "id")).delete()


@operation("groups.members")
async def groups_members(host: Host, arguments: dict[str, Any]) -> Any:
    group = _uuid(arguments, "id")
    await _require_group(host, group)
    return _entities(await host.engine.database.group_memberships.where(group_id=group))


@operation("groups.add_member")
async def groups_add_member(host: Host, arguments: dict[str, Any]) -> Any:
    await _require_group(host, _uuid(arguments, "id"))
    data = _validated(GroupMembership.Create, arguments)
    return _serialize(await host.engine.database.group_memberships.create(data))


@operation("groups.remove_member")
async def groups_remove_member(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.database.group_memberships.where(
        group_id=_uuid(arguments, "id"), user_id=_uuid(arguments, "user_id")
    ).delete()


@operation("memberships.list")
async def memberships_list(host: Host, arguments: dict[str, Any]) -> Any:
    return _entities(
        await host.engine.database.group_memberships.where(user_id=_uuid(arguments, "user_id"))
    )


@operation("memberships.add")
async def memberships_add(host: Host, arguments: dict[str, Any]) -> Any:
    await _require_group(host, _uuid(arguments, "group_id"))
    data = validate(
        GroupMembership.Create,
        {"user_id": _uuid(arguments, "user_id"), "group_id": _uuid(arguments, "group_id")},
    )
    return _serialize(await host.engine.database.group_memberships.create(data))


@operation("memberships.remove")
async def memberships_remove(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.database.group_memberships.where(
        user_id=_uuid(arguments, "user_id"), group_id=_uuid(arguments, "group_id")
    ).delete()


@operation("permissions.user")
async def permissions_user(host: Host, arguments: dict[str, Any]) -> Any:
    return _entities(
        await permission_handlers.get_user_permissions(
            engine=host.engine, user_id=_uuid(arguments, "user_id")
        )
    )


@operation("permissions.group")
async def permissions_group(host: Host, arguments: dict[str, Any]) -> Any:
    return _entities(
        await permission_handlers.get_group_permissions(
            engine=host.engine, group_id=_uuid(arguments, "group_id")
        )
    )


@operation("permissions.assign_user")
async def permissions_assign_user(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(permission_handlers.UserPermissionData, arguments)
    return _serialize(
        await permission_handlers.set_user_permission(
            engine=host.engine, user_id=_uuid(arguments, "user_id"), data=data
        )
    )


@operation("permissions.delete_user")
async def permissions_delete_user(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(permission_handlers.DeletePermissionData, arguments)
    return await permission_handlers.delete_user_permission(
        engine=host.engine, user_id=_uuid(arguments, "user_id"), data=data
    )


@operation("permissions.assign_group")
async def permissions_assign_group(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(permission_handlers.GroupPermissionData, arguments)
    return _serialize(
        await permission_handlers.set_group_permission(
            engine=host.engine, group_id=_uuid(arguments, "group_id"), data=data
        )
    )


@operation("permissions.delete_group")
async def permissions_delete_group(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(permission_handlers.DeletePermissionData, arguments)
    return await permission_handlers.delete_group_permission(
        engine=host.engine, group_id=_uuid(arguments, "group_id"), data=data
    )


@operation("permissions.effective")
async def permissions_effective(host: Host, arguments: dict[str, Any]) -> Any:
    return _entities(
        await permission_handlers.get_all_effective_access(
            engine=host.engine, user_id=_uuid(arguments, "user_id")
        )
    )


@operation("permissions.effective_at")
async def permissions_effective_at(host: Host, arguments: dict[str, Any]) -> Any:
    resolved = await permission_handlers.get_effective_access(
        engine=host.engine,
        user_id=_uuid(arguments, "user_id"),
        address=_address(arguments),
    )
    return _serialize(resolved)


@operation("workspaces.list")
async def workspaces_list(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    user = await _require_user(host, arguments)
    filter = _filter(WorkspaceFilter, arguments, 1000)
    return _entities(
        await workspace_handlers.get_workspaces(
            engine=host.engine, actor=actor, user=user, filter=filter
        )
    )


@operation("workspaces.get")
async def workspaces_get(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    user = await _require_user(host, arguments)
    found = await workspace_handlers.get_workspace(
        engine=host.engine, actor=actor, user=user, id=_uuid(arguments, "id")
    )
    return _serialize(found)


@operation("workspaces.create")
async def workspaces_create(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    user = await _require_user(host, arguments)
    data = _validated(Workspace.Create, arguments)
    return _serialize(
        await workspace_handlers.create_workspace(
            engine=host.engine, actor=actor, user=user, workspace=data
        )
    )


@operation("workspaces.update")
async def workspaces_update(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    user = await _require_user(host, arguments)
    data = _validated(Workspace.Update, arguments)
    return _serialize(
        await workspace_handlers.update_workspace(
            engine=host.engine,
            actor=actor,
            user=user,
            id=_uuid(arguments, "id"),
            update=data,
        )
    )


@operation("workspaces.delete")
async def workspaces_delete(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    user = await _require_user(host, arguments)
    return _serialize(
        await workspace_handlers.delete_workspace(
            engine=host.engine, actor=actor, user=user, id=_uuid(arguments, "id")
        )
    )


@operation("edits.list")
async def edits_list(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    filter = _filter(WorkspaceEditFilter, arguments, 1000)
    return _entities(
        await edit_handlers.get_workspace_edits(
            engine=host.engine,
            actor=actor,
            user_id=_uuid(arguments, "user_id"),
            filter=filter,
        )
    )


@operation("edits.get")
async def edits_get(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    found = await edit_handlers.get_workspace_edit(
        engine=host.engine,
        actor=actor,
        user_id=_uuid(arguments, "user_id"),
        workspace_id=_uuid(arguments, "workspace_id"),
    )
    return _serialize(found)


@operation("edits.create")
async def edits_create(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(edit_handlers.CreateWorkspaceEditData, arguments)
    return _serialize(
        await edit_handlers.create_workspace_edit(
            engine=host.engine,
            user_id=_uuid(arguments, "user_id"),
            workspace_id=_uuid(arguments, "workspace_id"),
            values=data,
        )
    )


@operation("edits.assign")
async def edits_assign(host: Host, arguments: dict[str, Any]) -> Any:
    data = _validated(edit_handlers.AssignWorkspaceEditData, arguments)
    return _serialize(
        await edit_handlers.assign_workspace_edit(
            engine=host.engine,
            user_id=_uuid(arguments, "user_id"),
            workspace_id=_uuid(arguments, "workspace_id"),
            values=data,
        )
    )


@operation("edits.delete")
async def edits_delete(host: Host, arguments: dict[str, Any]) -> Any:
    return _serialize(
        await edit_handlers.delete_workspace_edit(
            engine=host.engine,
            user_id=_uuid(arguments, "user_id"),
            workspace_id=_uuid(arguments, "workspace_id"),
        )
    )


@operation("settings.get")
async def settings_get(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    found = await setting_handlers.get_setting(
        engine=host.engine,
        actor=actor,
        user=actor.user,
        user_id=_uuid(arguments, "user_id"),
        name=validate(Name, _path(arguments, "name")),
    )
    return _serialize(found)


@operation("settings.assign")
async def settings_assign(host: Host, arguments: dict[str, Any]) -> Any:
    actor = await _actor(host, arguments)
    data = _validated(Setting.Create, arguments)
    return _serialize(
        await setting_handlers.put_setting(
            engine=host.engine, actor=actor, user=actor.user, setting=data
        )
    )
