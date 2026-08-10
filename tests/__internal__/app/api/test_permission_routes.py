from uuid import uuid4

import pytest
from pydantic import ValidationError

from ceres import Component, Engine
from ceres.__internal__.app.handlers.permissions import (
    UserPermissionData,
    get_all_effective_access,
    get_effective_access,
)
from ceres.__internal__.app.shared import build_address_chain
from ceres.address import Address
from ceres.component import ComponentAccessLevel, ComponentConfig
from ceres.error import NotFoundError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User


async def _build_engine() -> tuple[Engine, Component, Component, Component]:
    """Build an engine with a root and two children: `@granted` and `@hidden`.

    `@hidden` denies access by default so it is only visible to a user with an explicit grant.
    """
    engine = Engine()
    await engine.database.migrate()

    root = Component(__with_name__="root")
    granted = Component(__with_name__="granted")
    hidden = Component(
        __with_config__=ComponentConfig(name="hidden", access=ComponentAccessLevel.DENY)
    )

    engine.attach(root)
    root.system.attach(granted)
    root.system.attach(hidden)

    return engine, root, granted, hidden


async def _create_user(engine: Engine, *, admin: bool = False) -> User:
    unique = uuid4()
    return await engine.database.users.create(
        User.Create(
            username=f"user-{'admin' if admin else 'plain'}-{unique}",
            email=f"user-{unique}@test.com",
            password="hashed",
            admin=admin,
        )
    )


async def _grant_operate(engine: Engine, user: User, component: Component) -> None:
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target=str(component.system.address),
            level=ComponentAccessLevel.OPERATE,
        )
    )


async def test_batch_effective_access_lists_accessible_components() -> None:
    """A user with an operate grant on `@granted` sees only that component in the results."""
    engine, root, granted, hidden = await _build_engine()
    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)

    result = await get_all_effective_access(engine=engine, user_id=user.id)

    entries = {str(entry.address): entry.level for entry in result}
    assert entries[str(granted.system.address)] == ComponentAccessLevel.OPERATE
    assert str(hidden.system.address) not in entries

    await engine.database.dispose()


async def test_batch_effective_access_admin_sees_manage_everywhere() -> None:
    """An admin querying their own access sees every component resolved to manage."""
    engine, root, granted, hidden = await _build_engine()
    admin = await _create_user(engine, admin=True)

    result = await get_all_effective_access(engine=engine, user_id=admin.id)

    entries = {str(entry.address): entry.level for entry in result}
    assert entries[str(root.system.address)] == ComponentAccessLevel.MANAGE
    assert entries[str(granted.system.address)] == ComponentAccessLevel.MANAGE
    assert entries[str(hidden.system.address)] == ComponentAccessLevel.MANAGE

    await engine.database.dispose()


async def test_batch_effective_access_resolves_the_target_users_grants() -> None:
    """The route resolves the access of the user named in the path, whoever the caller is.

    The self-or-admin gate lives on the route dependency and is covered by
    `test_self_or_admin_forbids_querying_another_user`.
    """
    engine, root, granted, hidden = await _build_engine()
    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)

    result = await get_all_effective_access(engine=engine, user_id=user.id)

    entries = {str(entry.address): entry.level for entry in result}
    assert entries[str(granted.system.address)] == ComponentAccessLevel.OPERATE
    assert str(hidden.system.address) not in entries

    await engine.database.dispose()


async def test_batch_effective_access_missing_user_not_found() -> None:
    """Querying a nonexistent user raises a not-found error."""
    engine, root, granted, hidden = await _build_engine()

    with pytest.raises(NotFoundError):
        await get_all_effective_access(engine=engine, user_id=uuid4())

    await engine.database.dispose()


async def test_single_effective_access_route_still_matches_with_address() -> None:
    """The existing single-address route still resolves correctly alongside the new batch route."""
    engine, root, granted, hidden = await _build_engine()
    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)

    result = await get_effective_access(
        engine=engine,
        user_id=user.id,
        address=Address(str(granted.system.address)),
    )

    assert result.level == ComponentAccessLevel.OPERATE

    await engine.database.dispose()


async def test_batch_effective_access_includes_the_engine_root() -> None:
    """The engine root is a placement of its own so it is listed alongside the components."""
    engine, *_ = await _build_engine()
    user = await _create_user(engine)

    result = await get_all_effective_access(engine=engine, user_id=user.id)

    entries = {str(entry.address): entry.level for entry in result}
    assert entries["~"] == ComponentAccessLevel.VIEW

    await engine.database.dispose()


async def test_batch_effective_access_raises_the_engine_root_with_an_all_grant() -> None:
    """An all-target grant is what confers engine-level manage, without the user being an admin."""
    engine, *_ = await _build_engine()
    user = await _create_user(engine)
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.MANAGE,
        )
    )

    result = await get_all_effective_access(engine=engine, user_id=user.id)

    entries = {str(entry.address): entry.level for entry in result}
    assert entries["~"] == ComponentAccessLevel.MANAGE

    await engine.database.dispose()


async def test_single_effective_access_resolves_the_engine_root() -> None:
    """The single-address route accepts `~` rather than treating it as a missing component."""
    engine, *_ = await _build_engine()
    user = await _create_user(engine)

    result = await get_effective_access(engine=engine, user_id=user.id, address=Address("~"))

    assert result.level == ComponentAccessLevel.VIEW

    await engine.database.dispose()


def test_permission_data_accepts_all_target_type_with_empty_target() -> None:
    """An explicit empty `target` is valid for an 'all' grant."""
    data = UserPermissionData(
        target_type=PermissionTargetType.ALL, target="", level=ComponentAccessLevel.VIEW
    )
    assert data.target == ""


def test_permission_data_accepts_all_target_type_with_omitted_target() -> None:
    """Omitting `target` entirely is also valid for an 'all' grant, it defaults to empty."""
    data = UserPermissionData(target_type=PermissionTargetType.ALL, level=ComponentAccessLevel.VIEW)
    assert data.target == ""


def test_permission_data_rejects_all_target_type_with_nonempty_target() -> None:
    """An 'all' grant with a non-empty target is rejected."""
    with pytest.raises(ValidationError):
        UserPermissionData(
            target_type=PermissionTargetType.ALL, target="x", level=ComponentAccessLevel.VIEW
        )


def test_permission_data_rejects_invalid_component_address() -> None:
    """A `component` grant with a malformed address is rejected."""
    with pytest.raises(ValidationError):
        UserPermissionData(
            target_type=PermissionTargetType.COMPONENT,
            target="not a valid address!",
            level=ComponentAccessLevel.VIEW,
        )


def test_permission_data_rejects_bare_root_component_target() -> None:
    """A `component` grant targeting bare `@` is rejected, `@` no longer parses as an `Address`.

    This is a 422 at the route layer, `UserPermissionData` validation raises before the PUT
    handler runs.
    """
    with pytest.raises(ValidationError):
        UserPermissionData(
            target_type=PermissionTargetType.COMPONENT,
            target="@",
            level=ComponentAccessLevel.VIEW,
        )


def test_permission_data_rejects_empty_tag_target() -> None:
    """A `tag` grant with an empty target is rejected."""
    with pytest.raises(ValidationError):
        UserPermissionData(
            target_type=PermissionTargetType.TAG, target="", level=ComponentAccessLevel.VIEW
        )


def test_build_address_chain_stops_at_top_level_component() -> None:
    """The chain walks from a component up to its top-level ancestor, with no bare `@` entry."""
    sensor = Component(__with_name__="sensor")
    motor = Component(__with_name__="motor")
    sensor.system.attach(motor)

    assert build_address_chain(motor.system) == ["@sensor.motor", "@sensor"]
