"""The engine operations the native server dispatches to.

Every operation is a thin adapter over the engine and query layer, validating its
arguments through the same Pydantic models the API always used, so filters, permissions,
redaction, and wire shapes are unchanged by the transport moving to Rust. Arguments
arrive as `{"actor", "path", "query", "body"}`, and results leave as JSON-compatible
values the server serves verbatim.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any, cast

from ceres.__internal__.app.host import Host, operation, stream
from ceres.__internal__.app.shared import Actor, Limit, exclude_recursively
from ceres.address import Address
from ceres.alert import Alert
from ceres.component import ComponentFilter
from ceres.data import Name, to_json, validate
from ceres.error import NotFoundError, NotPermittedError, simplify
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.particle import Particle

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping, Sequence
    from uuid import UUID

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
    from uuid import UUID as Parse

    return Parse(_path(arguments, name))


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
        from uuid import UUID as Parse

        user = await host.engine.users.get(Parse(str(identifier)))

    return Actor(user=user, unrestricted=bool(described.get("unrestricted")))


async def _require_user(host: Host, arguments: dict[str, Any]) -> Any:
    """Return the concrete user behind the actor, refusing when there is none."""
    actor = await _actor(host, arguments)
    if actor.user is None:
        raise NotPermittedError()

    return actor.user


def _serialize(value: Any, exclude: Any = None) -> Any:
    """Render a value as JSON-compatible data, honoring a field exclusion."""
    return json.loads(to_json(value, exclude=exclude))


def _entities(values: Sequence[Any], exclude: Any = None) -> list[Any]:
    return [_serialize(value, exclude) for value in values]


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
    from ceres_core import RecordBatch

    from ceres.__internal__.app.shared import RECORD_TABLES

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
            from ceres.logs import get_logger

            get_logger("ceres.database").warning(
                f"Native record fetch fell back to the query layer. {error}"
            )

    if batch is None:
        batch = RecordBatch.parse(table, await query.mappings())

    return json.loads(batch.to_json())


@operation("records.count")
async def records_count(host: Host, arguments: dict[str, Any]) -> Any:
    Record, _ = _record_type(arguments)
    filter = _filter(Record.Filter, arguments)
    return await host.engine.__manager__(Record).where(filter).count()


@operation("records.get")
async def records_get(host: Host, arguments: dict[str, Any]) -> Any:
    from uuid import UUID as Parse

    Record, _ = _record_type(arguments)
    filter = Record.Filter(id=Parse(str(arguments["id"])))
    record = await host.engine.__manager__(Record).where(filter).first()
    if record is None:
        raise NotFoundError()

    return _serialize(record)


@stream("records.stream")
async def records_stream(host: Host, arguments: dict[str, Any]) -> AsyncIterator[str]:
    """Stream live records, serializing natively where the wire format allows."""
    from ceres_core import RecordBatch

    from ceres.__internal__.app.shared import RECORD_TABLES

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

    @operation(f"engine.{name}")
    async def control(host: Host, arguments: dict[str, Any]) -> Any:
        from ceres.__internal__.app import api

        handlers = {
            "start": api.start,
            "stop": api.stop,
            "enable": api.enable,
            "disable": api.disable,
            "up": api.up,
            "down": api.down,
        }
        filter = _validated(ComponentFilter, arguments)
        actor = await _actor(host, arguments)
        return _serialize(await handlers[name](engine=host.engine, actor=actor, filter=filter))

    return control


for _name in ("start", "stop", "enable", "disable", "up", "down"):
    _control(_name)


@operation("engine.reload")
async def engine_reload(host: Host, arguments: dict[str, Any]) -> Any:
    return simplify(await host.engine.reload())


@operation("users.list")
async def users_list(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.user import UserFilter

    filter = _filter(UserFilter, arguments, 1000)
    return _entities(await host.engine.users.where(filter), EXCLUDE_PASSWORDS)


@operation("users.count")
async def users_count(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.user import UserFilter

    return await host.engine.users.where(_filter(UserFilter, arguments)).count()


@operation("users.get")
async def users_get(host: Host, arguments: dict[str, Any]) -> Any:
    user = await host.engine.users.get(_uuid(arguments, "id"))
    if user is None:
        raise NotFoundError()

    return _serialize(user, EXCLUDE_PASSWORDS)


@operation("users.create")
async def users_create(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.user import User

    data = _validated(User.Create, arguments)
    return _serialize(await host.engine.users.create(data), EXCLUDE_PASSWORDS)


@operation("users.update")
async def users_update(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.user import User

    actor = await _actor(host, arguments)
    data = _validated(User.Update, arguments)

    # Only administrators may change another account's standing.
    supplied = _body(arguments) or {}
    if not actor.admin and ("admin" in supplied or "disabled" in supplied):
        raise NotPermittedError()

    id = _uuid(arguments, "id")
    await host.engine.users.where(id=id).update(data)
    return _serialize(await host.engine.users.get(id), EXCLUDE_PASSWORDS)


@operation("users.delete")
async def users_delete(host: Host, arguments: dict[str, Any]) -> Any:
    user = await host.engine.users.get(_uuid(arguments, "id"))
    if user is None:
        raise NotFoundError()

    await host.engine.users.where(id=user.id).delete()
    return _serialize(user, EXCLUDE_PASSWORDS)


@operation("statistics.list")
async def statistics_list(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.statistics import StatisticsFilter

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
    from ceres.__internal__.app.api.routes.components import get_components

    actor = await _actor(host, arguments)
    return _entities(await get_components(engine=host.engine, actor=actor))


@operation("components.get")
async def components_get(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.components import get_component

    actor = await _actor(host, arguments)
    described = await get_component(engine=host.engine, actor=actor, address=_address(arguments))
    return _serialize(described)


@operation("components.config")
async def components_config(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.components import get_component_config

    actor = await _actor(host, arguments)
    config = await get_component_config(
        engine=host.engine, actor=actor, address=_address(arguments)
    )
    return None if config is None else json.loads(to_json(config, exclude_defaults=True))


@operation("components.connections")
async def components_connections(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.components import get_component_connections

    actor = await _actor(host, arguments)
    return _entities(
        await get_component_connections(
            engine=host.engine, actor=actor, address=_address(arguments)
        )
    )


@operation("components.jobs")
async def components_jobs(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.components import get_component_jobs

    actor = await _actor(host, arguments)
    return _entities(
        await get_component_jobs(engine=host.engine, actor=actor, address=_address(arguments))
    )


@operation("components.send")
async def components_send(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.components import SendMessageInput, send_message

    actor = await _actor(host, arguments)
    data = _validated(SendMessageInput, arguments)
    sent = await send_message(
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
        binding = bindings.get(_path(arguments, "name"))
        if binding is None:
            raise NotFoundError()

        return _serialize(binding)

    return listing, single


for _namespace in ("procedures", "queries", "actions"):
    _bindings(_namespace)


def _calls(namespace: str):
    """Register the call operations for one namespace, by body and by query."""

    async def call(host: Host, arguments: dict[str, Any], method: str) -> Any:
        from typing import cast

        from ceres.__internal__.app.api.routes.components import call_natively

        actor = await _actor(host, arguments)
        if method == "GET":
            supplied = _pairs(arguments)
            supplied.pop("arguments", None)
            supplied.pop("args", None)
        else:
            supplied = _body(arguments)

        result = await call_natively(
            engine=host.engine,
            actor=actor,
            address=_address(arguments),
            procedure=validate(Name, _path(arguments, "name")),
            arguments=supplied,
            namespace=cast("Any", namespace),
            method=method,
        )
        return _serialize(result)

    @operation(f"{namespace}.call")
    async def by_body(host: Host, arguments: dict[str, Any]) -> Any:
        return await call(host, arguments, "POST")

    @operation(f"{namespace}.call_get")
    async def by_query(host: Host, arguments: dict[str, Any]) -> Any:
        return await call(host, arguments, "GET")

    @stream(f"{namespace}.subscribe")
    async def subscription(host: Host, arguments: dict[str, Any]) -> AsyncIterator[str]:
        from typing import cast

        from ceres.__internal__.app.api.routes.components import subscribe_natively

        actor = await _actor(host, arguments)
        async for output in subscribe_natively(
            engine=host.engine,
            actor=actor,
            address=_address(arguments),
            procedure=validate(Name, _path(arguments, "name")),
            arguments=_pairs(arguments),
            namespace=cast("Any", namespace),
        ):
            yield to_json(output)

    return by_body, by_query, subscription


for _namespace in ("procedures", "queries", "actions"):
    _calls(_namespace)


@operation("groups.list")
async def groups_list(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.group import GroupFilter

    return _entities(await host.engine.database.groups.where(_filter(GroupFilter, arguments, 1000)))


@operation("groups.count")
async def groups_count(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.group import GroupFilter

    return await host.engine.database.groups.where(_filter(GroupFilter, arguments)).count()


@operation("groups.get")
async def groups_get(host: Host, arguments: dict[str, Any]) -> Any:
    found = await host.engine.database.groups.get(_uuid(arguments, "id"))
    if found is None:
        raise NotFoundError()

    return _serialize(found)


@operation("groups.create")
async def groups_create(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.group import Group

    data = _validated(Group.Create, arguments)
    return _serialize(await host.engine.database.groups.create(data))


@operation("groups.update")
async def groups_update(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.group import Group

    data = _validated(Group.Update, arguments)
    return await host.engine.database.groups.where(id=_uuid(arguments, "id")).update(data)


@operation("groups.delete")
async def groups_delete(host: Host, arguments: dict[str, Any]) -> Any:
    return await host.engine.database.groups.where(id=_uuid(arguments, "id")).delete()


@operation("groups.members")
async def groups_members(host: Host, arguments: dict[str, Any]) -> Any:

    return _entities(
        await host.engine.database.group_memberships.where(group_id=_uuid(arguments, "id"))
    )


@operation("groups.add_member")
async def groups_add_member(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.group import GroupMembership

    body = dict(_body(arguments) or {})
    body["group_id"] = str(_uuid(arguments, "id"))
    data = validate(GroupMembership.Create, body)
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
    from ceres.group import GroupMembership

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
    from ceres.__internal__.app.api.routes.permissions import get_user_permissions

    return _entities(
        await get_user_permissions(engine=host.engine, user_id=_uuid(arguments, "user_id"))
    )


@operation("permissions.group")
async def permissions_group(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import get_group_permissions

    return _entities(
        await get_group_permissions(engine=host.engine, group_id=_uuid(arguments, "group_id"))
    )


@operation("permissions.assign_user")
async def permissions_assign_user(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import (
        UserPermissionData,
        set_user_permission,
    )

    data = _validated(UserPermissionData, arguments)
    return _serialize(
        await set_user_permission(
            engine=host.engine, user_id=_uuid(arguments, "user_id"), data=data
        )
    )


@operation("permissions.delete_user")
async def permissions_delete_user(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import (
        DeletePermissionData,
        delete_user_permission,
    )

    data = _validated(DeletePermissionData, arguments)
    return await delete_user_permission(
        engine=host.engine, user_id=_uuid(arguments, "user_id"), data=data
    )


@operation("permissions.assign_group")
async def permissions_assign_group(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import (
        GroupPermissionData,
        set_group_permission,
    )

    data = _validated(GroupPermissionData, arguments)
    return _serialize(
        await set_group_permission(
            engine=host.engine, group_id=_uuid(arguments, "group_id"), data=data
        )
    )


@operation("permissions.delete_group")
async def permissions_delete_group(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import (
        DeletePermissionData,
        delete_group_permission,
    )

    data = _validated(DeletePermissionData, arguments)
    return await delete_group_permission(
        engine=host.engine, group_id=_uuid(arguments, "group_id"), data=data
    )


@operation("permissions.effective")
async def permissions_effective(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import get_all_effective_access

    return _entities(
        await get_all_effective_access(engine=host.engine, user_id=_uuid(arguments, "user_id"))
    )


@operation("permissions.effective_at")
async def permissions_effective_at(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.permissions import get_effective_access

    resolved = await get_effective_access(
        engine=host.engine,
        user_id=_uuid(arguments, "user_id"),
        address=_address(arguments),
    )
    return _serialize(resolved)


def _workspace_operations() -> None:
    """Register the workspace operations, each keeping its placement rules."""
    from ceres.__internal__.app.api.routes import workspaces as routes

    @operation("workspaces.list")
    async def listing(host: Host, arguments: dict[str, Any]) -> Any:
        from ceres.workspace import WorkspaceFilter

        actor = await _actor(host, arguments)
        user = await _require_user(host, arguments)
        filter = _filter(WorkspaceFilter, arguments, 1000)
        return _entities(
            await routes.get_workspaces(engine=host.engine, actor=actor, user=user, filter=filter)
        )

    @operation("workspaces.get")
    async def single(host: Host, arguments: dict[str, Any]) -> Any:
        actor = await _actor(host, arguments)
        user = await _require_user(host, arguments)
        found = await routes.get_workspace(
            engine=host.engine, actor=actor, user=user, id=_uuid(arguments, "id")
        )
        return _serialize(found)

    @operation("workspaces.create")
    async def creating(host: Host, arguments: dict[str, Any]) -> Any:
        from ceres.workspace import Workspace

        actor = await _actor(host, arguments)
        user = await _require_user(host, arguments)
        data = _validated(Workspace.Create, arguments)
        return _serialize(
            await routes.create_workspace(
                engine=host.engine, actor=actor, user=user, workspace=data
            )
        )

    @operation("workspaces.update")
    async def updating(host: Host, arguments: dict[str, Any]) -> Any:
        from ceres.workspace import Workspace

        actor = await _actor(host, arguments)
        user = await _require_user(host, arguments)
        data = _validated(Workspace.Update, arguments)
        return _serialize(
            await routes.update_workspace(
                engine=host.engine,
                actor=actor,
                user=user,
                id=_uuid(arguments, "id"),
                update=data,
            )
        )

    @operation("workspaces.delete")
    async def deleting(host: Host, arguments: dict[str, Any]) -> Any:
        actor = await _actor(host, arguments)
        user = await _require_user(host, arguments)
        return _serialize(
            await routes.delete_workspace(
                engine=host.engine, actor=actor, user=user, id=_uuid(arguments, "id")
            )
        )


_workspace_operations()


def _edit_operations() -> None:
    """Register the per-user workspace edit operations."""
    from ceres.__internal__.app.api.routes import workspace_edits as routes

    @operation("edits.list")
    async def listing(host: Host, arguments: dict[str, Any]) -> Any:
        from ceres.workspace import WorkspaceEditFilter

        actor = await _actor(host, arguments)
        filter = _filter(WorkspaceEditFilter, arguments, 1000)
        return _entities(
            await routes.get_workspace_edits(
                engine=host.engine,
                actor=actor,
                user_id=_uuid(arguments, "user_id"),
                filter=filter,
            )
        )

    @operation("edits.get")
    async def single(host: Host, arguments: dict[str, Any]) -> Any:
        actor = await _actor(host, arguments)
        found = await routes.get_workspace_edit(
            engine=host.engine,
            actor=actor,
            user_id=_uuid(arguments, "user_id"),
            workspace_id=_uuid(arguments, "workspace_id"),
        )
        return _serialize(found)

    @operation("edits.create")
    async def creating(host: Host, arguments: dict[str, Any]) -> Any:
        data = _validated(routes.CreateWorkspaceEditData, arguments)
        return _serialize(
            await routes.create_workspace_edit(
                engine=host.engine,
                user_id=_uuid(arguments, "user_id"),
                workspace_id=_uuid(arguments, "workspace_id"),
                values=data,
            )
        )

    @operation("edits.assign")
    async def assigning(host: Host, arguments: dict[str, Any]) -> Any:
        data = _validated(routes.AssignWorkspaceEditData, arguments)
        return _serialize(
            await routes.assign_workspace_edit(
                engine=host.engine,
                user_id=_uuid(arguments, "user_id"),
                workspace_id=_uuid(arguments, "workspace_id"),
                values=data,
            )
        )

    @operation("edits.delete")
    async def deleting(host: Host, arguments: dict[str, Any]) -> Any:
        return _serialize(
            await routes.delete_workspace_edit(
                engine=host.engine,
                user_id=_uuid(arguments, "user_id"),
                workspace_id=_uuid(arguments, "workspace_id"),
            )
        )


_edit_operations()


@operation("settings.get")
async def settings_get(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.settings import get_setting

    actor = await _actor(host, arguments)
    found = await get_setting(
        engine=host.engine,
        actor=actor,
        user=actor.user,
        user_id=_uuid(arguments, "user_id"),
        name=validate(Name, _path(arguments, "name")),
    )
    return _serialize(found)


@operation("settings.assign")
async def settings_assign(host: Host, arguments: dict[str, Any]) -> Any:
    from ceres.__internal__.app.api.routes.settings import put_setting
    from ceres.setting import Setting

    actor = await _actor(host, arguments)
    data = _validated(Setting.Create, arguments)
    return _serialize(
        await put_setting(engine=host.engine, actor=actor, user=actor.user, setting=data)
    )
