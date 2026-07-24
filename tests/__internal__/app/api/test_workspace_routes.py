import pytest

from ceres import Engine
from ceres.__internal__.app.api.routes.workspace_memberships import (
    WorkspaceMembershipCreateData,
    create_workspace_membership,
)
from ceres.__internal__.app.api.routes.workspaces import (
    create_workspace,
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
from ceres.workspace import (
    Workspace,
    WorkspaceAccessLevel,
    WorkspaceFilter,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)


async def _build_engine() -> Engine:
    engine = Engine()
    await engine.database.migrate()
    return engine


async def _create_user(engine: Engine, username: str) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed")
    )


async def _create_workspace(engine: Engine, name: str) -> Workspace:
    return await engine.workspaces.create(
        Workspace.Create(
            name=name,
            general_viewership=WorkspaceAccessLevel.PRIVATE,
            general_editorship=WorkspaceAccessLevel.PRIVATE,
            general_managership=WorkspaceAccessLevel.PRIVATE,
        )
    )


async def _add_member(
    engine: Engine,
    user: User,
    workspace: Workspace,
    role: WorkspaceMembershipRole,
) -> None:
    await engine.workspace_memberships.create(
        WorkspaceMembership.Create(user_id=user.id, workspace_id=workspace.id, role=role)
    )


async def _build_engine_with_component(access: str | None = None) -> Engine:
    engine = Engine()
    await engine.database.migrate()
    component: dict[str, object] = {"name": "rig", "class": "ceres.component:Component"}
    if access is not None:
        component["access"] = access

    config = validate(Config, {"components": [component]})
    await engine.load(config, checks=())
    return engine


async def _grant(engine: Engine, user: User, target: str, level: ComponentAccessLevel) -> None:
    await engine.database.user_permissions.create(
        UserPermission.Create(
            user_id=user.id,
            target_type=PermissionTargetType.COMPONENT,
            target=target,
            level=level,
        )
    )


async def test_editor_of_another_workspace_cannot_update_a_private_workspace() -> None:
    """Editing rights on one workspace must not allow updates to an unrelated workspace."""
    engine = await _build_engine()
    editor = await _create_user(engine, "editor")
    own = await _create_workspace(engine, "own")
    other = await _create_workspace(engine, "other")
    await _add_member(engine, editor, own, WorkspaceMembershipRole.EDITOR)

    with pytest.raises(NotFoundError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=editor, unrestricted=False),
            user=editor,
            id=other.id,
            update={"data": {}},
        )

    await engine.database.dispose()


async def test_editor_cannot_change_general_editorship() -> None:
    """Changing workspace access settings requires manager-level membership."""
    engine = await _build_engine()
    editor = await _create_user(engine, "editor")
    workspace = await _create_workspace(engine, "shared")
    await _add_member(engine, editor, workspace, WorkspaceMembershipRole.EDITOR)

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=editor, unrestricted=False),
            user=editor,
            id=workspace.id,
            update={"general_editorship": WorkspaceAccessLevel.ANYONE},
        )

    await engine.database.dispose()


async def test_manager_can_change_general_editorship() -> None:
    engine = await _build_engine()
    manager = await _create_user(engine, "manager")
    workspace = await _create_workspace(engine, "shared")
    await _add_member(engine, manager, workspace, WorkspaceMembershipRole.MANAGER)

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=manager, unrestricted=False),
        user=manager,
        id=workspace.id,
        update={"general_editorship": WorkspaceAccessLevel.ANYONE},
    )

    assert updated.general_editorship == WorkspaceAccessLevel.ANYONE

    await engine.database.dispose()


async def test_editor_can_update_workspace_data() -> None:
    engine = await _build_engine()
    editor = await _create_user(engine, "editor")
    workspace = await _create_workspace(engine, "shared")
    await _add_member(engine, editor, workspace, WorkspaceMembershipRole.EDITOR)

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=editor, unrestricted=False),
        user=editor,
        id=workspace.id,
        update={"data": {"widgets": []}},
    )

    assert updated.data == {"widgets": []}

    await engine.database.dispose()


async def test_scoped_workspace_visible_with_view_on_scope() -> None:
    engine = await _build_engine_with_component()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    result = await get_workspace(
        engine=engine, actor=Actor(user=user, unrestricted=False), user=user, id=workspace.id
    )
    assert result.id == workspace.id

    await engine.database.dispose()


async def test_scoped_workspace_hidden_without_view_on_scope() -> None:
    engine = await _build_engine_with_component(access="deny")
    user = await _create_user(engine, "outsider")
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    with pytest.raises(NotFoundError):
        await get_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            id=workspace.id,
        )

    await engine.database.dispose()


async def test_scoped_workspace_update_requires_manage() -> None:
    engine = await _build_engine_with_component()
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=user, unrestricted=False),
            user=user,
            id=workspace.id,
            update={"data": {}},
        )

    await engine.database.dispose()


async def test_scoped_workspace_update_allowed_with_manage() -> None:
    engine = await _build_engine_with_component()
    user = await _create_user(engine, "manager")
    await _grant(engine, user, "@rig", ComponentAccessLevel.MANAGE)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    result = await update_workspace(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        id=workspace.id,
        update={"data": {"layout": []}},
    )
    assert result.data == {"layout": []}

    await engine.database.dispose()


async def test_create_scoped_workspace_requires_manage_and_skips_membership() -> None:
    engine = await _build_engine_with_component()
    manager = await _create_user(engine, "manager")
    viewer = await _create_user(engine, "viewer")
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)
    await _grant(engine, viewer, "@rig", ComponentAccessLevel.VIEW)

    with pytest.raises(NotPermittedError):
        await create_workspace(
            engine=engine,
            actor=Actor(user=viewer, unrestricted=False),
            user=viewer,
            workspace=Workspace.Create(name="rig-dash", scope=Address("@rig")),
        )

    created = await create_workspace(
        engine=engine,
        actor=Actor(user=manager, unrestricted=False),
        user=manager,
        workspace=Workspace.Create(name="rig-dash", scope=Address("@rig")),
    )
    assert created.scope == Address("@rig")
    assert await engine.workspace_memberships.get(manager.id, created.id) is None

    await engine.database.dispose()


async def test_memberships_rejected_on_scoped_workspace() -> None:
    engine = await _build_engine_with_component()
    manager = await _create_user(engine, "manager")
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    with pytest.raises(NotPermittedError):
        await create_workspace_membership(
            engine=engine,
            user=manager,
            user_id=manager.id,
            workspace_id=workspace.id,
            data=WorkspaceMembershipCreateData(role=WorkspaceMembershipRole.VIEWER),
        )

    await engine.database.dispose()


async def test_list_includes_scoped_only_with_view() -> None:
    engine = await _build_engine_with_component(access="deny")
    user = await _create_user(engine, "viewer")
    visible = await engine.workspaces.create(
        Workspace.Create(name="visible", scope=Address("@rig"))
    )
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        filter=WorkspaceFilter(),
    )
    assert [workspace.id for workspace in listed] == [visible.id]

    await engine.database.dispose()


async def test_editor_of_global_workspace_cannot_rescope_to_component() -> None:
    """An editor lacks manage access on `@rig`, so rescoping the workspace must be rejected."""
    engine = await _build_engine_with_component()
    editor = await _create_user(engine, "editor")
    workspace = await _create_workspace(engine, "shared")
    await _add_member(engine, editor, workspace, WorkspaceMembershipRole.EDITOR)

    with pytest.raises(NotPermittedError):
        await update_workspace(
            engine=engine,
            actor=Actor(user=editor, unrestricted=False),
            user=editor,
            id=workspace.id,
            update={"scope": Address("@rig")},
        )

    await engine.database.dispose()


async def test_unscoping_workspace_grants_caller_manager_membership() -> None:
    engine = await _build_engine_with_component()
    manager = await _create_user(engine, "manager")
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=manager, unrestricted=False),
        user=manager,
        id=workspace.id,
        update={"scope": None},
    )
    assert updated.scope is None

    membership = await engine.workspace_memberships.get(manager.id, workspace.id)
    assert membership is not None
    assert membership.role == WorkspaceMembershipRole.MANAGER

    await engine.database.dispose()


async def test_list_excludes_scoped_workspace_when_scope_not_viewable() -> None:
    engine = Engine()
    await engine.database.migrate()
    config = validate(
        Config,
        {
            "components": [
                {"name": "rig", "class": "ceres.component:Component"},
                {"name": "vault", "class": "ceres.component:Component", "access": "deny"},
            ]
        },
    )
    await engine.load(config, checks=())
    user = await _create_user(engine, "viewer")
    visible = await engine.workspaces.create(
        Workspace.Create(name="visible", scope=Address("@rig"))
    )
    await engine.workspaces.create(Workspace.Create(name="hidden", scope=Address("@vault")))
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user=user,
        filter=WorkspaceFilter(),
    )
    assert [workspace.id for workspace in listed] == [visible.id]

    await engine.database.dispose()
