import pytest

from ceres import Engine
from ceres.__internal__.app.api.routes.workspaces import update_workspace
from ceres.__internal__.app.shared import Actor
from ceres.error import NotFoundError, NotPermittedError
from ceres.user import User
from ceres.workspace import (
    Workspace,
    WorkspaceAccessLevel,
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
