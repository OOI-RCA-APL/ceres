from ceres import Engine
from ceres.__internal__.app.shared import get_engine_access, get_engine_access_detail
from ceres.access import AccessSource, GrantOrigin
from ceres.config import ComponentAccessLevel, Config
from ceres.data import validate
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User


async def _build_engine(access: str | None = None) -> Engine:
    engine = Engine()
    await engine.database.migrate()
    payload: dict[str, object] = {"components": []}
    if access is not None:
        payload["access"] = access

    await engine.load(validate(Config, payload), checks=())
    return engine


async def _create_user(engine: Engine, username: str, admin: bool = False) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed", admin=admin)
    )


async def test_authenticated_user_can_view_the_engine_by_default() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")

    assert await get_engine_access(engine, user) == ComponentAccessLevel.VIEW

    await engine.database.dispose()


async def test_unauthenticated_caller_has_no_engine_access() -> None:
    engine = await _build_engine()

    assert await get_engine_access(engine, None) is None

    await engine.database.dispose()


async def test_all_target_grant_raises_engine_access() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "operator")
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.MANAGE,
        )
    )

    assert await get_engine_access(engine, user) == ComponentAccessLevel.MANAGE

    await engine.database.dispose()


async def test_config_default_lowers_engine_access() -> None:
    """A denying default reads as no access, the same as it does on a component."""
    engine = await _build_engine(access="deny")
    user = await _create_user(engine, "viewer")

    assert await get_engine_access(engine, user) is None

    await engine.database.dispose()


async def test_engine_access_detail_names_what_conferred_the_level() -> None:
    engine = await _build_engine(access="deny")
    user = await _create_user(engine, "operator")
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.MANAGE,
        )
    )

    resolved = await get_engine_access_detail(engine, user)
    assert resolved is not None
    assert resolved.level == ComponentAccessLevel.MANAGE
    assert resolved.source == AccessSource.ALL
    assert resolved.origin == GrantOrigin.USER

    await engine.database.dispose()


async def test_all_target_grant_overrides_a_denying_config_default() -> None:
    """A grant is how an operator opens up an engine that defaults to closed."""
    engine = await _build_engine(access="deny")
    user = await _create_user(engine, "viewer")
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.ALL,
            target="",
            level=ComponentAccessLevel.VIEW,
        )
    )

    assert await get_engine_access(engine, user) == ComponentAccessLevel.VIEW

    await engine.database.dispose()


async def test_admin_manages_the_engine() -> None:
    engine = await _build_engine(access="deny")
    admin = await _create_user(engine, "admin", admin=True)

    assert await get_engine_access(engine, admin) == ComponentAccessLevel.MANAGE

    await engine.database.dispose()
