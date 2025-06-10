from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from ceres._internal.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentRole,
    RequireViewer,
    assert_found,
)
from ceres.error import Failure, NotPermittedError
from ceres.user import UserRole
from ceres.workspace import (
    Workspace,
    WorkspaceCreate,
    WorkspaceFilter,
    WorkspaceMembershipCreate,
    WorkspaceMembershipRole,
    WorkspaceUpdate,
)

router = APIRouter(tags=["workspaces"])


class GetWorkspaceQueryParameters(WorkspaceFilter):
    limit: int = Field(default=100, ge=0, le=1000)


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
    filter: Annotated[GetWorkspaceQueryParameters, Query()],
) -> list[Workspace]:
    scope = WorkspaceFilter.model_validate(filter, from_attributes=True)
    if user is not None and role < UserRole.ADMIN:
        scope &= WorkspaceFilter(viewable_by=user.id)

    return await engine.workspaces.where(scope)


@router.get("/users/{user_id:uuid}/workspaces", dependencies=[SELF_OR_ADMIN])
async def get_workspaces_for_user(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[GetWorkspaceQueryParameters, Query()],
) -> list[Workspace]:
    return await engine.workspaces.where(joined_by=user_id, and__=filter)


@router.post("/workspaces")
async def create_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: RequireViewer,
    workspace: WorkspaceCreate,
) -> Workspace:
    workspace = await engine.workspaces.create(workspace)
    if user is not None:
        await engine.workspace_memberships.create(
            WorkspaceMembershipCreate(
                user_id=user.id,
                workspace_id=workspace.id,
                role=WorkspaceMembershipRole.OWNER,
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
    if role < UserRole.ADMIN and user is not None:
        if (
            "default_viewership" in update
            or "default_editorship" in update
            or "default_ownership" in update
        ):
            # Only owners can change default roles.
            membership = await engine.workspace_memberships.get(user.id, id)
            if membership is None or membership.role < WorkspaceMembershipRole.OWNER:
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
    scope = WorkspaceFilter()
    if user is not None and role < UserRole.ADMIN:
        # Only workspace owners and admins can delete a workspaces.
        scope = WorkspaceFilter(ownable_by=user.id)

    return assert_found(await engine.workspaces.where(id=id).delete().first())
