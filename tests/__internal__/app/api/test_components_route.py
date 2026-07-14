from ceres import Component, Engine
from ceres.__internal__.app.api.routes.components import get_components
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentConfig
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User

_UNRESTRICTED = Actor(user=None, unrestricted=True)


async def _build_engine() -> tuple[Engine, Component, Component]:
    """Build an engine with two top-level components: `@alpha` and `@beta`.

    `@alpha` has a single child, `@alpha.child`.
    """
    engine = Engine()
    await engine.database.migrate()

    alpha = Component(__with_name__="alpha")
    beta = Component(__with_name__="beta")
    child = Component(__with_name__="child")

    engine.attach(alpha)
    engine.attach(beta)
    alpha.system.attach(child)

    return engine, alpha, beta


async def test_get_components_returns_one_entry_per_top_level_component() -> None:
    """`GET /api/components` returns one entry per top-level component, not their children."""
    engine, alpha, beta = await _build_engine()

    result = await get_components(engine=engine, actor=_UNRESTRICTED)

    addresses = {str(info.address) for info in result}
    assert addresses == {str(alpha.system.address), str(beta.system.address)}

    await engine.database.dispose()


async def test_get_components_recursively_populates_children() -> None:
    """Each top-level entry has its descendants nested under `components`."""
    engine, alpha, beta = await _build_engine()

    result = await get_components(engine=engine, actor=_UNRESTRICTED)

    alpha_info = next(info for info in result if str(info.address) == str(alpha.system.address))
    child_addresses = {str(child.address) for child in alpha_info.components}
    assert child_addresses == {"@alpha.child"}

    await engine.database.dispose()


async def _build_restricted_engine() -> tuple[Engine, Component]:
    """Build an engine whose `@rack` tree denies access by default, with a viewable `@rack.sensor`."""
    engine = Engine()
    await engine.database.migrate()

    rack = Component(
        __with_name__="rack",
        __with_config__=ComponentConfig(name="rack", access=ComponentAccessLevel.DENY),
    )
    sensor = Component(__with_name__="sensor")
    motor = Component(__with_name__="motor")

    engine.attach(rack)
    rack.system.attach(sensor)
    rack.system.attach(motor)

    return engine, sensor


async def test_get_components_hides_components_without_view_access() -> None:
    """A user with a grant only on `@rack.sensor` sees it, but not its denied sibling `@rack.motor`."""
    engine, sensor = await _build_restricted_engine()
    user = await engine.database.users.create(
        User.Create(username="viewer", email="viewer@test.com", password="hashed", admin=False)
    )
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target="@rack.sensor",
            level=ComponentAccessLevel.VIEW,
        )
    )

    result = await get_components(engine=engine, actor=Actor(user=user, unrestricted=False))

    # The denied `@rack` ancestor is returned only as a container leading to the visible sensor.
    assert len(result) == 1
    rack_info = result[0]
    assert str(rack_info.address) == "@rack"
    assert rack_info.procedures == []
    assert rack_info.connections == []
    child_addresses = {str(child.address) for child in rack_info.components}
    assert child_addresses == {"@rack.sensor"}


async def test_get_components_empty_for_user_with_no_access() -> None:
    """A user with no grants sees nothing when every component denies access by default."""
    engine, _ = await _build_restricted_engine()
    user = await engine.database.users.create(
        User.Create(username="nobody", email="nobody@test.com", password="hashed", admin=False)
    )

    result = await get_components(engine=engine, actor=Actor(user=user, unrestricted=False))

    assert result == []
