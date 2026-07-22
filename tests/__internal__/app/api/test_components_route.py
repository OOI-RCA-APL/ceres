import pytest

from ceres import Address, Component, Engine, action
from ceres.__internal__.app.api.routes.components import (
    get_component_config,
    get_component_jobs,
    get_components,
)
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentConfig
from ceres.config import JobConfig
from ceres.data import create, validate
from ceres.error import NotFoundError, NotPermittedError
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


async def _create_user(engine: Engine, username: str) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed", admin=False)
    )


async def _grant(engine: Engine, user: User, target: str, level: ComponentAccessLevel) -> None:
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target=target,
            level=level,
        )
    )


async def test_get_component_config_returns_the_component_config() -> None:
    """An unrestricted caller receives the component's own configuration."""
    engine = Engine()
    await engine.database.migrate()
    engine.attach(
        Component(
            __with_name__="rack",
            __with_config__=ComponentConfig(name="rack", tags=["hardware"]),
        )
    )

    result = await get_component_config(
        engine=engine, actor=_UNRESTRICTED, address=Address("@rack")
    )

    assert result is not None
    assert result.name == "rack"
    assert result.tags == ["hardware"]


async def test_get_component_config_requires_access() -> None:
    """A user with no access to the component cannot read its configuration."""
    engine, sensor = await _build_restricted_engine()
    user = await _create_user(engine, "nobody")

    with pytest.raises(NotPermittedError):
        await get_component_config(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            address=sensor.system.address,
        )


async def test_get_component_config_allowed_with_view_access() -> None:
    """Any access to the component is enough to read its configuration."""
    engine, sensor = await _build_restricted_engine()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rack.sensor", ComponentAccessLevel.VIEW)

    result = await get_component_config(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        address=sensor.system.address,
    )

    assert result is None or result.name == "sensor"


async def test_get_component_config_rejects_an_unknown_address() -> None:
    """An address with no matching component is a not-found, not a permission failure."""
    engine, _ = await _build_restricted_engine()

    with pytest.raises(NotFoundError):
        await get_component_config(engine=engine, actor=_UNRESTRICTED, address=Address("@missing"))


class _JobbedComponent(Component):
    @action
    async def poke(self) -> None:
        pass


async def test_get_component_jobs_describes_each_job() -> None:
    """Each configured job is returned with its schedule and no next run while stopped."""
    engine = Engine()
    await engine.database.migrate()
    job = validate(JobConfig, {"name": "poke", "action": "poke", "schedule": "0 * * * *"})
    config = create(ComponentConfig, {"name": "jobbed", "jobs": [job]})
    engine.attach(_JobbedComponent(__with_name__="jobbed", __with_config__=config))

    result = await get_component_jobs(
        engine=engine, actor=_UNRESTRICTED, address=Address("@jobbed")
    )

    assert len(result) == 1
    assert result[0].name == "poke"
    assert result[0].action == "poke"
    assert result[0].schedule == "0 * * * *"
    assert result[0].next_run is None


async def test_get_component_jobs_requires_access() -> None:
    """A user with no access to the component cannot list its jobs."""
    engine, sensor = await _build_restricted_engine()
    user = await _create_user(engine, "nobody")

    with pytest.raises(NotPermittedError):
        await get_component_jobs(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            address=sensor.system.address,
        )


async def test_get_component_jobs_empty_without_jobs() -> None:
    """A component with no configured jobs returns an empty list."""
    engine, sensor = await _build_restricted_engine()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rack.sensor", ComponentAccessLevel.VIEW)

    result = await get_component_jobs(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        address=sensor.system.address,
    )

    assert result == []
