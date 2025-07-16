from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field
from sqlalchemy.util.typing import TypedDict

from ceres._internal.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentUser,
    RequireViewer,
    assert_found,
)
from ceres.data import DeferBuild, ImmutableDataObject
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import UserRole
from ceres.workspace import (
    WorkspaceFilter,
    WorkspaceMembership,
    WorkspaceMembershipFilter,
    WorkspaceMembershipRole,
    WorkspaceMembershipUpdate,
)

router = APIRouter(tags=["workspace-memberships"])


class GetWorkspaceMembershipsQueryParameters(WorkspaceMembershipFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get(
    "/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def get_workspace_membership(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    return assert_found(await engine.workspace_memberships.get(user_id, workspace_id))


@router.get("/users/{user_id:uuid}/workspace-memberships", dependencies=[SELF_OR_ADMIN])
async def get_workspace_memberships(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[GetWorkspaceMembershipsQueryParameters, Query()],
) -> list[WorkspaceMembership]:
    return await engine.workspace_memberships.where(user_id=user_id, and__=filter)


@router.get("/workspaces/{workspace_id:uuid}/memberships")
async def get_workspace_memberships_in_workspace(
    engine: CurrentEngine,
    user: RequireViewer,
    workspace_id: UUID,
    filter: Annotated[GetWorkspaceMembershipsQueryParameters, Query()],
) -> list[WorkspaceMembership]:
    if user is not None and user.role < UserRole.ADMIN:
        if not await engine.workspaces.where(viewable_by=user.id).any():
            raise Failure(NotFoundError)

    return await engine.workspace_memberships.where(workspace_id=workspace_id, and__=filter)


async def _guard_membership_mutation(
    engine: CurrentEngine,
    user: CurrentUser,
    workspace_id: UUID,
    workspace_role: WorkspaceMembershipRole | None,
) -> None:
    if user is not None and user.role < UserRole.ADMIN:
        if workspace_role is None:
            return

        match workspace_role:
            case WorkspaceMembershipRole.VIEWER:
                filter = WorkspaceFilter(viewable_by=user.id)
            case WorkspaceMembershipRole.EDITOR:
                filter = WorkspaceFilter(editable_by=user.id)
            case WorkspaceMembershipRole.MANAGER:
                filter = WorkspaceFilter(manageable_by=user.id)

        if not await engine.workspaces.where(id=workspace_id, and__=filter).any():
            raise Failure(NotPermittedError)


class WorkspaceMembershipCreateData(ImmutableDataObject, DeferBuild):
    role: WorkspaceMembershipRole


@router.post(
    "/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def create_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
    data: WorkspaceMembershipCreateData,
) -> WorkspaceMembership:
    await _guard_membership_mutation(engine, user, workspace_id, data.role)
    return await engine.workspace_memberships.create(
        WorkspaceMembership(
            user_id=user_id,
            workspace_id=workspace_id,
            role=data.role,
        ),
    )


class WorkspaceMembershipUpdateData(TypedDict, total=False):
    role: WorkspaceMembershipRole


@router.patch(
    "/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def update_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
    assign: WorkspaceMembershipUpdate,
) -> WorkspaceMembership:
    if "role" in assign:
        await _guard_membership_mutation(engine, user, workspace_id, assign["role"])

    return assert_found(
        await engine.workspace_memberships.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .update(assign)
        .first()
    )


@router.delete("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def delete_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    if user is not None and user.role < UserRole.ADMIN and user.id != user_id:
        # Only editors or admins can delete memberships for other users.
        membership = await engine.workspace_memberships.get(user.id, workspace_id)
        if membership is None or membership.role < WorkspaceMembershipRole.EDITOR:
            raise Failure(NotPermittedError)

    return assert_found(
        await engine.workspace_memberships.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .delete()
        .first()
    )
