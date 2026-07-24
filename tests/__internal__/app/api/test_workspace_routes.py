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
    get_workspaces_for_user,
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


async def _build_engine_with_component(access: str | None = None, secret: bool = False) -> Engine:
    engine = Engine()
    await engine.database.migrate()
    component: dict[str, object] = {"name": "rig", "class": "ceres.component:Component"}
    if access is not None:
        component["access"] = access

    components: list[dict[str, object]] = [component]
    if secret:
        components.append(
            {"name": "secret", "class": "ceres.component:Component", "access": "deny"}
        )

    config = validate(Config, {"components": components})
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


async def test_workspaces_for_user_hides_scoped_workspace_without_scope_access() -> None:
    """A stale membership on a scoped workspace must not leak the workspace through the user
    listing endpoint. `_guard_membership_mutation` blocks new memberships on scoped workspaces,
    but a membership can still be left over from before the workspace gained its scope.
    """
    engine = await _build_engine_with_component(access="deny")
    user = await _create_user(engine, "bob")
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )
    await engine.workspace_memberships.create(
        WorkspaceMembership.Create(
            user_id=user.id, workspace_id=workspace.id, role=WorkspaceMembershipRole.VIEWER
        )
    )

    results = await get_workspaces_for_user(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user_id=user.id,
        filter=WorkspaceFilter(),
    )
    assert results == []

    await engine.database.dispose()


async def test_workspaces_for_user_includes_scoped_workspace_with_scope_access() -> None:
    engine = await _build_engine_with_component()
    user = await _create_user(engine, "bob")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(
        Workspace.Create(name="rig-dash", scope=Address("@rig"))
    )
    await engine.workspace_memberships.create(
        WorkspaceMembership.Create(
            user_id=user.id, workspace_id=workspace.id, role=WorkspaceMembershipRole.VIEWER
        )
    )

    results = await get_workspaces_for_user(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user_id=user.id,
        filter=WorkspaceFilter(),
    )
    assert [result.id for result in results] == [workspace.id]

    await engine.database.dispose()


async def test_rescoping_workspace_deletes_existing_memberships() -> None:
    """Rescoping a global workspace to a component must drop its memberships. Scoped workspaces
    derive access from their component, so a leftover membership would otherwise leak visibility
    through `get_workspaces_for_user`.
    """
    engine = await _build_engine_with_component()
    manager = await _create_user(engine, "manager")
    viewer = await _create_user(engine, "viewer")
    workspace = await _create_workspace(engine, "ops")
    await _add_member(engine, manager, workspace, WorkspaceMembershipRole.MANAGER)
    await _add_member(engine, viewer, workspace, WorkspaceMembershipRole.VIEWER)
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)

    updated = await update_workspace(
        engine=engine,
        actor=Actor(user=manager, unrestricted=False),
        user=manager,
        id=workspace.id,
        update={"scope": Address("@rig")},
    )
    assert updated.scope == Address("@rig")

    assert await engine.workspace_memberships.get(manager.id, workspace.id) is None
    assert await engine.workspace_memberships.get(viewer.id, workspace.id) is None

    await engine.database.dispose()


async def test_workspace_response_redacts_denied_widget() -> None:
    engine = await _build_engine_with_component(secret=True)
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(
        Workspace.Create(
            name="dash",
            scope=Address("@rig"),
            data={
                "layout": [
                    {
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "button",
                                "name": "Peek",
                                "address": "@secret",
                                "action": "peek",
                                "width": 60,
                            }
                        ]
                    }
                ]
            },
        )
    )

    result = await get_workspace(
        engine=engine, actor=Actor(user=user, unrestricted=False), user=user, id=workspace.id
    )
    widget = result.data["layout"][0]["widgets"][0]
    assert widget["restricted"] is True
    assert "address" not in widget

    await engine.database.dispose()


async def test_update_scoped_workspace_preserves_config_behind_redacted_stub() -> None:
    """Round-tripping a redacted GET through PATCH must not destroy the real widget config
    stored behind a stub. The caller has manage on the scope but no view on `@secret`.
    """
    engine = await _build_engine_with_component(secret=True)
    manager = await _create_user(engine, "manager")
    await _grant(engine, manager, "@rig", ComponentAccessLevel.MANAGE)
    workspace = await engine.workspaces.create(
        Workspace.Create(
            name="dash",
            scope=Address("@rig"),
            data={
                "layout": [
                    {
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "button",
                                "name": "Peek",
                                "address": "@secret",
                                "action": "peek",
                                "arguments": {"depth": 1},
                                "width": 60,
                            }
                        ]
                    }
                ]
            },
        )
    )

    fetched = await get_workspace(
        engine=engine, actor=Actor(user=manager, unrestricted=False), user=manager, id=workspace.id
    )
    stub = fetched.data["layout"][0]["widgets"][0]
    assert stub["restricted"] is True

    await update_workspace(
        engine=engine,
        actor=Actor(user=manager, unrestricted=False),
        user=manager,
        id=workspace.id,
        update={"data": fetched.data},
    )

    stored = await engine.workspaces.where(id=workspace.id).first()
    assert stored is not None
    widget = stored.data["layout"][0]["widgets"][0]
    assert widget["address"] == "@secret"
    assert widget["action"] == "peek"
    assert widget["arguments"] == {"depth": 1}

    await engine.database.dispose()


async def test_update_global_workspace_preserves_config_behind_redacted_stub() -> None:
    """The same stub-preservation guarantee applies to global workspaces, since redaction
    applies to them too.
    """
    engine = await _build_engine_with_component(secret=True)
    editor = await _create_user(engine, "editor")
    workspace = await engine.workspaces.create(
        Workspace.Create(
            name="ops",
            data={
                "layout": [
                    {
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "button",
                                "name": "Peek",
                                "address": "@secret",
                                "action": "peek",
                                "width": 60,
                            }
                        ]
                    }
                ]
            },
        )
    )
    await _add_member(engine, editor, workspace, WorkspaceMembershipRole.EDITOR)

    fetched = await get_workspace(
        engine=engine, actor=Actor(user=editor, unrestricted=False), user=editor, id=workspace.id
    )
    assert fetched.data["layout"][0]["widgets"][0]["restricted"] is True

    await update_workspace(
        engine=engine,
        actor=Actor(user=editor, unrestricted=False),
        user=editor,
        id=workspace.id,
        update={"data": fetched.data},
    )

    stored = await engine.workspaces.where(id=workspace.id).first()
    assert stored is not None
    widget = stored.data["layout"][0]["widgets"][0]
    assert widget["address"] == "@secret"
    assert widget["action"] == "peek"

    await engine.database.dispose()


async def test_workspace_response_not_redacted_for_admin() -> None:
    engine = await _build_engine_with_component()
    admin = await _create_user(engine, "boss")
    workspace = await engine.workspaces.create(
        Workspace.Create(
            name="dash",
            scope=Address("@rig"),
            data={
                "layout": [
                    {
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "button",
                                "address": "@rig",
                                "name": "Go",
                                "width": 60,
                            }
                        ]
                    }
                ]
            },
        )
    )

    result = await get_workspace(
        engine=engine, actor=Actor(user=admin, unrestricted=True), user=admin, id=workspace.id
    )
    assert result.data["layout"][0]["widgets"][0]["address"] == "@rig"

    await engine.database.dispose()
