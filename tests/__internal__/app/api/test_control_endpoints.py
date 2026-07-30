from ceres import Component, Engine
from ceres.__internal__.app.handlers.engine import disable, down, enable, start, stop, up
from ceres.__internal__.app.shared import Actor
from ceres.component import ComponentAccessLevel, ComponentFilter
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User


async def _build_engine() -> tuple[Engine, Component, Component, Component]:
    """Build an engine with a root and two children: `@granted` and `@restricted`."""
    engine = Engine()
    await engine.database.migrate()

    root = Component(__with_name__="root")
    granted = Component(__with_name__="granted")
    restricted = Component(__with_name__="restricted")

    engine.attach(root)
    root.system.attach(granted)
    root.system.attach(restricted)

    return engine, root, granted, restricted


async def _create_user(engine: Engine, *, admin: bool = False) -> User:
    return await engine.database.users.create(
        User.Create(
            username=f"user-{'admin' if admin else 'plain'}-{id(engine)}",
            email=f"user-{id(engine)}-{admin}@test.com",
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


async def _teardown(engine: Engine, *components: Component) -> None:
    """Stop any still-running components and dispose the engine's database connection."""
    for component in components:
        if component.system.running:
            await component.system.stop()
    await engine.database.dispose()


async def test_start_skips_components_without_operate_access() -> None:
    """A user with an operate grant on only `@granted` starts only that component."""
    engine, root, granted, restricted = await _build_engine()
    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await start(engine, actor, ComponentFilter())

    assert result.started == [granted.system.address]
    assert granted.system.running
    assert not restricted.system.running

    await _teardown(engine, root, granted, restricted)


async def test_start_allows_admin_everywhere() -> None:
    """An admin actor starts every stopped component regardless of grants."""
    engine, root, granted, restricted = await _build_engine()
    admin = await _create_user(engine, admin=True)
    actor = Actor(user=admin, unrestricted=False)

    result = await start(engine, actor, ComponentFilter())

    expected = [root.system.address, granted.system.address, restricted.system.address]
    assert sorted(result.started) == sorted(expected)

    await _teardown(engine, root, granted, restricted)


async def test_start_unrestricted_actor_starts_everything() -> None:
    """CLI mode (unrestricted actor) bypasses per-component checks entirely."""
    engine, root, granted, restricted = await _build_engine()
    actor = Actor(user=None, unrestricted=True)

    result = await start(engine, actor, ComponentFilter())

    expected = [root.system.address, granted.system.address, restricted.system.address]
    assert sorted(result.started) == sorted(expected)

    await _teardown(engine, root, granted, restricted)


async def test_start_user_without_any_grant_starts_nothing() -> None:
    """A user with no grants at all starts nothing, since the default access is view."""
    engine, root, granted, restricted = await _build_engine()
    user = await _create_user(engine)
    actor = Actor(user=user, unrestricted=False)

    result = await start(engine, actor, ComponentFilter())

    assert result.started == []
    assert not granted.system.running
    assert not restricted.system.running

    await _teardown(engine, root, granted, restricted)


async def test_stop_skips_components_without_operate_access() -> None:
    engine, root, granted, restricted = await _build_engine()
    granted.system.start()
    restricted.system.start()

    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await stop(engine, actor, ComponentFilter())

    assert result.stopped == [granted.system.address]
    assert not granted.system.running
    assert restricted.system.running

    await _teardown(engine, root, granted, restricted)


async def test_enable_skips_components_without_operate_access() -> None:
    engine, root, granted, restricted = await _build_engine()
    await granted.system.disable()
    await restricted.system.disable()

    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await enable(engine, actor, ComponentFilter())

    assert result.enabled == [granted.system.address]
    assert granted.system.enabled
    assert not restricted.system.enabled

    await _teardown(engine, root, granted, restricted)


async def test_disable_skips_components_without_operate_access() -> None:
    engine, root, granted, restricted = await _build_engine()
    await granted.system.enable()
    await restricted.system.enable()

    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await disable(engine, actor, ComponentFilter())

    assert result.disabled == [granted.system.address]
    assert not granted.system.enabled
    assert restricted.system.enabled

    await _teardown(engine, root, granted, restricted)


async def test_up_skips_components_without_operate_access() -> None:
    engine, root, granted, restricted = await _build_engine()
    await granted.system.disable()
    await restricted.system.disable()

    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await up(engine, actor, ComponentFilter())

    assert result.enabled == [granted.system.address]
    assert result.started == [granted.system.address]
    assert granted.system.enabled
    assert granted.system.running
    assert not restricted.system.enabled
    assert not restricted.system.running

    await _teardown(engine, root, granted, restricted)


async def test_down_skips_components_without_operate_access() -> None:
    engine, root, granted, restricted = await _build_engine()
    await granted.system.enable()
    await restricted.system.enable()
    granted.system.start()
    restricted.system.start()

    user = await _create_user(engine)
    await _grant_operate(engine, user, granted)
    actor = Actor(user=user, unrestricted=False)

    result = await down(engine, actor, ComponentFilter())

    assert result.disabled == [granted.system.address]
    assert result.stopped == [granted.system.address]
    assert not granted.system.enabled
    assert not granted.system.running
    assert restricted.system.enabled
    assert restricted.system.running

    await _teardown(engine, root, granted, restricted)
