import pytest

from ceres import Engine
from ceres.__internal__.app.handlers.workspaces import (
    build_can_view,
    get_workspace,
    get_workspaces,
    update_workspace,
)
from ceres.__internal__.app.operations import _require_not_disabled
from ceres.__internal__.app.shared import Actor
from ceres.address import Address
from ceres.config import ComponentAccessLevel, Config
from ceres.data import validate
from ceres.error import NotFoundError, NotPermittedError
from ceres.permission import PermissionTargetType, UserPermission
from ceres.user import User
from ceres.workspace import Workspace, WorkspaceFilter


async def _build_engine() -> Engine:
    engine = Engine()
    await engine.database.migrate()
    return engine


async def _create_user(engine: Engine, username: str) -> User:
    return await engine.database.users.create(
        User.Create(username=username, email=f"{username}@test.com", password="hashed")
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


async def test_workspace_response_redacts_video_widget_query_target() -> None:
    """A video widget's `query` field encodes a component address as
    `@component::queries::name`, that address must be redacted the same as any other target.
    """
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
                                "type": "video",
                                "name": "Feed",
                                "query": "@secret::queries::stream",
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
    assert "query" not in widget

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


async def test_unrestricted_actor_still_sees_shared_workspace_without_the_flag() -> None:
    engine = await _build_engine_with_component()
    workspace = await engine.workspaces.create(
        Workspace.Create(name="shared", scope=Address("@rig"))
    )

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=None, unrestricted=True),
        user=None,
        filter=WorkspaceFilter(),
    )
    assert [current.id for current in listed] == [workspace.id]

    await engine.database.dispose()


async def test_build_can_view_denies_every_component_for_anonymous_caller() -> None:
    engine = await _build_engine_with_component()
    can_view = await build_can_view(engine, None)

    assert can_view(Address("@rig")) is False
    assert can_view(Address("@missing")) is True

    await engine.database.dispose()


async def test_anonymous_listing_returns_only_public_workspaces() -> None:
    engine = await _build_engine_with_component()
    owner = await _create_user(engine, "owner")
    public = await engine.workspaces.create(
        Workspace.Create(name="public", show_when_logged_out=True)
    )
    await engine.workspaces.create(
        Workspace.Create(name="private", owner_id=owner.id, show_when_logged_out=True)
    )
    await engine.workspaces.create(Workspace.Create(name="shared"))

    listed = await get_workspaces(
        engine=engine,
        actor=Actor(user=None, unrestricted=False),
        user=None,
        filter=WorkspaceFilter(),
    )
    assert [workspace.id for workspace in listed] == [public.id]

    await engine.database.dispose()


async def test_anonymous_read_of_public_workspace_is_redacted() -> None:
    engine = await _build_engine_with_component(secret=True)
    workspace = await engine.workspaces.create(
        Workspace.Create(
            name="dash",
            show_when_logged_out=True,
            data={
                "layout": [
                    {
                        "widgets": [
                            {
                                "id": "w1",
                                "type": "particles",
                                "name": "Feed",
                                "address": "@secret",
                                "filter": {"address": "@secret"},
                                "width": 60,
                            }
                        ]
                    }
                ]
            },
        )
    )

    result = await get_workspace(
        engine=engine, actor=Actor(user=None, unrestricted=False), user=None, id=workspace.id
    )
    widget = result.data["layout"][0]["widgets"][0]
    assert widget["restricted"] is True
    assert "address" not in widget
    assert "filter" not in widget

    await engine.database.dispose()


async def test_anonymous_read_of_workspace_without_flag_is_not_found() -> None:
    engine = await _build_engine_with_component()
    workspace = await engine.workspaces.create(Workspace.Create(name="dash"))

    with pytest.raises(NotFoundError):
        await get_workspace(
            engine=engine, actor=Actor(user=None, unrestricted=False), user=None, id=workspace.id
        )

    await engine.database.dispose()


async def test_require_not_disabled_refuses_a_disabled_users_token() -> None:
    engine = await _build_engine()
    disabled = await engine.database.users.create(
        User.Create(
            username="disabled", email="disabled@test.com", password="hashed", disabled=True
        )
    )

    with pytest.raises(NotPermittedError):
        _require_not_disabled(Actor(user=disabled, unrestricted=False))

    await engine.database.dispose()
