from ceres import Engine
from ceres.__internal__.app.handlers.workspace_edits import (
    AssignWorkspaceEditData,
    assign_workspace_edit,
    get_workspace_edit,
)
from ceres.__internal__.app.shared import Actor
from ceres.address import Address
from ceres.config import ComponentAccessLevel, Config
from ceres.data import validate
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User
from ceres.workspace import Workspace, WorkspaceEditCreate


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


async def _create_user(engine: Engine, username: str) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed")
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


async def test_workspace_edit_response_redacts_denied_widget() -> None:
    engine = await _build_engine_with_component(secret=True)
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(Workspace.Create(name="dash", scope=Address("@rig")))
    await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user.id,
            workspace_id=workspace.id,
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

    result = await get_workspace_edit(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user_id=user.id,
        workspace_id=workspace.id,
    )
    widget = result.data["layout"][0]["widgets"][0]
    assert widget["restricted"] is True
    assert "address" not in widget

    await engine.database.dispose()


async def test_workspace_edit_response_not_redacted_for_admin() -> None:
    engine = await _build_engine_with_component()
    admin = await _create_user(engine, "boss")
    workspace = await engine.workspaces.create(Workspace.Create(name="dash", scope=Address("@rig")))
    await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=admin.id,
            workspace_id=workspace.id,
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

    result = await get_workspace_edit(
        engine=engine,
        actor=Actor(user=admin, unrestricted=True),
        user_id=admin.id,
        workspace_id=workspace.id,
    )
    assert result.data["layout"][0]["widgets"][0]["address"] == "@rig"

    await engine.database.dispose()


async def test_assign_workspace_edit_preserves_config_behind_redacted_stub() -> None:
    """Saving a workspace edit must not let a redaction stub round-tripped from a prior GET
    overwrite the real widget configuration already stored for that edit.
    """
    engine = await _build_engine_with_component(secret=True)
    user = await _create_user(engine, "viewer")
    await _grant(engine, user, "@rig", ComponentAccessLevel.VIEW)
    workspace = await engine.workspaces.create(Workspace.Create(name="dash", scope=Address("@rig")))
    await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user.id,
            workspace_id=workspace.id,
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

    fetched = await get_workspace_edit(
        engine=engine,
        actor=Actor(user=user, unrestricted=False),
        user_id=user.id,
        workspace_id=workspace.id,
    )
    assert fetched.data["layout"][0]["widgets"][0]["restricted"] is True

    await assign_workspace_edit(
        engine=engine,
        user_id=user.id,
        workspace_id=workspace.id,
        values=AssignWorkspaceEditData(data=fetched.data),
    )

    stored = await engine.workspace_edits.get(user.id, workspace.id)
    assert stored is not None
    widget = stored.data["layout"][0]["widgets"][0]
    assert widget["address"] == "@secret"
    assert widget["action"] == "peek"
    assert widget["arguments"] == {"depth": 1}

    await engine.database.dispose()


async def test_assign_workspace_edit_keeps_unrestricted_changes() -> None:
    engine = await _build_engine_with_component()
    user = await _create_user(engine, "viewer")
    workspace = await engine.workspaces.create(Workspace.Create(name="dash", scope=Address("@rig")))
    await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user.id,
            workspace_id=workspace.id,
            data={
                "layout": [
                    {
                        "widgets": [
                            {"id": "w1", "type": "button", "name": "Old", "width": 60},
                        ]
                    }
                ]
            },
        )
    )

    await assign_workspace_edit(
        engine=engine,
        user_id=user.id,
        workspace_id=workspace.id,
        values=AssignWorkspaceEditData(
            data={
                "layout": [
                    {
                        "widgets": [
                            {"id": "w1", "type": "button", "name": "New", "width": 60},
                        ]
                    }
                ]
            }
        ),
    )

    stored = await engine.workspace_edits.get(user.id, workspace.id)
    assert stored is not None
    assert stored.data["layout"][0]["widgets"][0]["name"] == "New"

    await engine.database.dispose()
