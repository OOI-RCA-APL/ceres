from typing import Annotated
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentRole,
    Limit,
    RequireViewer,
    Router,
    assert_found,
)
from ceres.error import NotFoundError, NotPermittedError
from ceres.user import UserRole
from ceres.workspace import (
    Workspace,
    WorkspaceCreate,
    WorkspaceFilter,
    WorkspaceMembershipCreate,
    WorkspaceMembershipRole,
    WorkspaceUpdate,
)

router = Router(tags=["workspaces"])


@router.get("/workspaces/{id:uuid}")
async def get_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    id: UUID,
) -> Workspace:
    """Return a single workspace by ID. Non-admin callers only see workspaces they can view.

    Raises:
        NotFoundError: If the workspace does not exist or the caller cannot view it.
    """
    scope = WorkspaceFilter(id=id)
    if user is not None and role < UserRole.ADMIN:
        scope &= WorkspaceFilter(viewable_by=user.id)

    return assert_found(await engine.workspaces.where(scope).first())


@router.get("/workspaces")
async def get_workspaces(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    filter: Annotated[WorkspaceFilter, Query(), Limit(1000)],
) -> list[Workspace]:
    """Return workspaces matching the given filter. Non-admin callers only see workspaces they
    can view, capped at 1000 results.
    """
    scope = WorkspaceFilter.model_validate(filter, from_attributes=True)
    if user is not None and role < UserRole.ADMIN:
        scope &= WorkspaceFilter(viewable_by=user.id)

    return await engine.workspaces.where(scope)


@router.get("/users/{user_id:uuid}/workspaces", dependencies=[SELF_OR_ADMIN])
async def get_workspaces_for_user(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[WorkspaceFilter, Query()],
) -> list[Workspace]:
    """Return workspaces that a specific user has joined, filtered by the given criteria."""
    return await engine.workspaces.where(joined_by=user_id, and__=filter)


@router.post("/workspaces")
async def create_workspace(
    engine: CurrentEngine,
    user: RequireViewer,
    workspace: WorkspaceCreate,
) -> Workspace:
    """Create a new workspace and grant the creating user a manager membership in it."""
    workspace = await engine.workspaces.create(workspace)
    if user is not None:
        await engine.workspace_memberships.create(
            WorkspaceMembershipCreate(
                user_id=user.id,
                workspace_id=workspace.id,
                role=WorkspaceMembershipRole.MANAGER,
            )
        )

    return workspace


@router.patch("/workspaces/{id:uuid}")
async def update_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    id: UUID,
    update: WorkspaceUpdate,
) -> Workspace:
    """Partially update a workspace. Changing name or viewership/managership settings requires
    manager-level access. Other updates require editor-level access.

    Raises:
        NotFoundError: If the workspace does not exist.
        NotPermittedError: If the caller lacks permission.
    """
    if user is not None and role < UserRole.ADMIN:
        if (
            "name" in update
            or "general_viewership" in update
            or "general_viewership" in update
            or "general_managership" in update
        ):
            if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
                raise NotFoundError()
            # Only managers and admins can change these workspace settings.
            membership = await engine.workspace_memberships.get(user.id, id)
            if membership is None or membership.role < WorkspaceMembershipRole.MANAGER:
                raise NotPermittedError()
        elif not await engine.workspaces.where(editable_by=user.id).any():
            # Only editors can update workspaces.
            raise NotPermittedError()

    return assert_found(await engine.workspaces.where(id=id).update(update).first())


@router.delete("/workspaces/{id:uuid}")
async def delete_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    id: UUID,
) -> Workspace:
    """Delete a workspace by ID. Only workspace managers and admins can delete workspaces.

    Raises:
        NotFoundError: If the workspace does not exist.
        NotPermittedError: If the caller lacks permission.
    """
    if user is not None and role < UserRole.ADMIN:
        if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
            raise NotFoundError()
        if not await engine.workspaces.where(id=id, manageable_by=user.id).any():
            # Only workspace managers and admins can delete a workspaces.
            raise NotPermittedError()

    return assert_found(await engine.workspaces.where(id=id).delete().first())
