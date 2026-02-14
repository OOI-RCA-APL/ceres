from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Query

from ceres._internal.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentRole,
    Limit,
    RequireViewer,
    Router,
    assert_found,
)
from ceres.error import Failure, NotFoundError, NotPermittedError
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
    return await engine.workspaces.where(joined_by=user_id, and__=filter)


@router.post("/workspaces")
async def create_workspace(
    engine: CurrentEngine,
    user: RequireViewer,
    workspace: WorkspaceCreate,
) -> Workspace:
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
    if user is not None and role < UserRole.ADMIN:
        if (
            "name" in update
            or "general_viewership" in update
            or "general_viewership" in update
            or "general_managership" in update
        ):
            if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
                raise Failure(NotFoundError)
            # Only managers and admins can change these workspace settings.
            membership = await engine.workspace_memberships.get(user.id, id)
            if membership is None or membership.role < WorkspaceMembershipRole.MANAGER:
                raise Failure(NotPermittedError)
        elif not await engine.workspaces.where(editable_by=user.id).any():
            # Only editors can update workspaces.
            raise Failure(NotPermittedError)

    return assert_found(await engine.workspaces.where(id=id).update(update).first())


@router.delete("/workspaces/{id:uuid}")
async def delete_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    id: UUID,
) -> Workspace:
    if user is not None and role < UserRole.ADMIN:
        if not await engine.workspaces.where(id=id, viewable_by=user.id).any():
            raise Failure(NotFoundError)
        if not await engine.workspaces.where(id=id, manageable_by=user.id).any():
            # Only workspace managers and admins can delete a workspaces.
            raise Failure(NotPermittedError)

    return assert_found(await engine.workspaces.where(id=id).delete().first())
