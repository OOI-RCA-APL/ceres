from ceres.database import Database
from ceres.user import User, UserRole
from ceres.workspace import (
    Workspace,
    WorkspaceAccessLevel,
    WorkspaceMembership,
    WorkspaceMembershipRole,
)


async def _setup_database() -> Database:
    database = Database()
    await database.init()
    return database


def test_access_levels_are_anyone_and_private() -> None:
    assert [level.value for level in WorkspaceAccessLevel] == ["anyone", "private"]


async def test_anyone_workspace_viewable_without_membership() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", role=UserRole.VIEWER)
    )
    workspace = await database.workspaces.create(
        Workspace.Create(name="open", general_viewership=WorkspaceAccessLevel.ANYONE)
    )
    found = await database.workspaces.where(viewable_by=user.id)
    assert workspace.id in {current.id for current in found}


async def test_private_workspace_hidden_without_membership() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", role=UserRole.VIEWER)
    )
    workspace = await database.workspaces.create(
        Workspace.Create(name="closed", general_viewership=WorkspaceAccessLevel.PRIVATE)
    )
    found = await database.workspaces.where(viewable_by=user.id)
    assert workspace.id not in {current.id for current in found}


async def test_private_workspace_visible_with_membership() -> None:
    database = await _setup_database()
    user = await database.users.create(
        User.Create(username="viewer", email="v@test.com", password="hashed", role=UserRole.VIEWER)
    )
    workspace = await database.workspaces.create(
        Workspace.Create(name="closed", general_viewership=WorkspaceAccessLevel.PRIVATE)
    )
    await database.workspace_memberships.create(
        WorkspaceMembership.Create(
            user_id=user.id, workspace_id=workspace.id, role=WorkspaceMembershipRole.VIEWER
        )
    )
    found = await database.workspaces.where(viewable_by=user.id)
    assert workspace.id in {current.id for current in found}


async def test_admin_role_does_not_grant_general_access() -> None:
    """An admin's `UserRole` no longer influences the general-access SQL directly.

    Route-layer admin bypass checks are handled separately from `WorkspaceFilter`.
    """
    database = await _setup_database()
    admin = await database.users.create(
        User.Create(username="admin", email="a@test.com", password="hashed", role=UserRole.ADMIN)
    )
    workspace = await database.workspaces.create(
        Workspace.Create(name="closed", general_viewership=WorkspaceAccessLevel.PRIVATE)
    )
    found = await database.workspaces.where(viewable_by=admin.id)
    assert workspace.id not in {current.id for current in found}
