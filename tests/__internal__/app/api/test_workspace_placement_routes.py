import pytest

from ceres import Engine
from ceres.__internal__.app.api.routes.workspaces import (
    create_workspace,
    delete_workspace,
    get_workspace,
    get_workspaces,
    update_workspace,
)
from ceres.__internal__.app.shared import Actor
from ceres.address import Address
from ceres.config import ComponentAccessLevel, Config
from ceres.data import validate
from ceres.error import NotFoundError, NotPermittedError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User
from ceres.workspace import Workspace, WorkspaceFilter


async def _build_engine(access: str | None = None) -> Engine:
    engine = Engine()
    await engine.database.migrate()
    component: dict[str, object] = {"name": "rig", "class": "ceres.component:Component"}
    if access is not None:
        component["access"] = access

    await engine.load(validate(Config, {"components": [component]}), checks=())
    return engine


async def _create_user(engine: Engine, username: str, admin: bool = False) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed", admin=admin)
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


async def test_view_access_creates_a_private_workspace() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    created = await create_workspace(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        workspace=Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=user.id),
    )

    assert created.owner_id == user.id

    await engine.database.dispose()


async def test_view_access_cannot_create_a_shared_workspace() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    with pytest.raises(NotPermittedError):
        await create_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            workspace=Workspace.Create(name="team", scope=Address("@rig")),
        )

    await engine.database.dispose()


async def test_a_caller_cannot_create_a_workspace_owned_by_somebody_else() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")
    other = await _create_user(engine, "other")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    with pytest.raises(NotPermittedError):
        await create_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            workspace=Workspace.Create(name="theirs", scope=Address("@rig"), owner_id=other.id),
        )

    await engine.database.dispose()


async def test_private_workspace_is_hidden_from_a_manager_of_the_same_component() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    manager = await _create_user(engine, "manager")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    with pytest.raises(NotFoundError):
        await get_workspace(
            engine=engine,
            actor=Actor(user=manager, unrestricted=False),
            user=manager,
            id=private.id,
        )

    await engine.database.dispose()


async def test_private_workspace_is_absent_from_admin_listings() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    admin = await _create_user(engine, "admin", admin=True)
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=admin, unrestricted=False),
        user=admin,
        filter=WorkspaceFilter(),
    )

    assert private.id not in {current.id for current in listed}

    await engine.database.dispose()


async def test_owner_sees_their_own_private_workspace_in_listings() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=owner, unrestricted=False),
        user=owner,
        filter=WorkspaceFilter(),
    )

    assert private.id in {current.id for current in listed}

    await engine.database.dispose()


async def test_owner_publishes_a_private_workspace_with_manage_access() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.MANAGE)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=owner, unrestricted=False),
        user=owner,
        id=private.id,
        update={"owner_id": None},
    )

    assert updated.owner_id is None

    await engine.database.dispose()


async def test_publishing_requires_manage_on_the_placement() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=owner, unrestricted=False),
            user=owner,
            id=private.id,
            update={"owner_id": None},
        )

    await engine.database.dispose()


async def test_a_shared_workspace_cannot_be_taken_private() -> None:
    engine = await _build_engine()
    manager = await _create_user(engine, "manager")
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)

    shared = await engine.workspaces.create(Workspace.Create(name="team", scope=Address("@rig")))

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=manager, unrestricted=False),
            user=manager,
            id=shared.id,
            update={"owner_id": manager.id},
        )

    await engine.database.dispose()


async def test_owner_losing_view_access_loses_the_workspace() -> None:
    engine = await _build_engine(access="deny")
    owner = await _create_user(engine, "owner")

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    with pytest.raises(NotFoundError):
        await get_workspace(
            engine=engine,
            actor=Actor(user=owner, unrestricted=False),
            user=owner,
            id=private.id,
        )

    await engine.database.dispose()


async def test_owner_edits_their_private_workspace_without_manage_access() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=owner, unrestricted=False),
        user=owner,
        id=private.id,
        update={"name": "renamed"},
    )

    assert updated.name == "renamed"

    await engine.database.dispose()


async def test_owner_deletes_their_private_workspace() -> None:
    engine = await _build_engine()
    owner = await _create_user(engine, "owner")
    await _grant(engine, owner, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=owner.id)
    )

    await delete_workspace(
        engine=engine,
        actor=Actor(user=owner, unrestricted=False),
        user=owner,
        id=private.id,
    )

    assert await engine.workspaces.where(id=private.id).first() is None

    await engine.database.dispose()


async def test_viewer_cannot_edit_a_shared_workspace() -> None:
    engine = await _build_engine()
    viewer = await _create_user(engine, "viewer")
    await _grant(engine, viewer, "@rig", ComponentAccessLevel.VIEW)

    shared = await engine.workspaces.create(Workspace.Create(name="team", scope=Address("@rig")))

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=viewer, unrestricted=False),
            user=viewer,
            id=shared.id,
            update={"name": "renamed"},
        )

    await engine.database.dispose()


async def test_engine_placed_workspace_is_visible_to_any_authenticated_user() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")

    home = await engine.workspaces.create(Workspace.Create(name="home"))

    found = await get_workspace(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        id=home.id,
    )

    assert found.id == home.id

    await engine.database.dispose()


async def test_creating_a_shared_engine_workspace_needs_an_all_target_grant() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")

    with pytest.raises(NotPermittedError):
        await create_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            workspace=Workspace.Create(name="home"),
        )

    await engine.database.dispose()


async def test_all_target_manage_grant_creates_a_shared_engine_workspace() -> None:
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

    created = await create_workspace(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        workspace=Workspace.Create(name="home"),
    )

    assert created.scope == Address("~")
    assert created.owner_id is None

    await engine.database.dispose()


async def test_any_user_creates_a_private_engine_workspace() -> None:
    """A personal home tab needs only the view every authenticated user has on the engine."""
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")

    created = await create_workspace(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        workspace=Workspace.Create(name="mine", owner_id=user.id),
    )

    assert created.owner_id == user.id
    assert created.scope == Address("~")

    await engine.database.dispose()


async def test_moving_a_workspace_requires_manage_on_the_destination() -> None:
    engine = await _build_engine()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    private = await engine.workspaces.create(
        Workspace.Create(name="scratch", scope=Address("@rig"), owner_id=user.id)
    )

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            id=private.id,
            update={"scope": Address("~")},
        )

    await engine.database.dispose()
