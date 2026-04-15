from typing import Annotated, TypedDict
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentUser,
    Limit,
    RequireViewer,
    Router,
    assert_found,
)
from ceres.data import DataObject
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import UserRole
from ceres.workspace import (
    WorkspaceFilter,
    WorkspaceMembership,
    WorkspaceMembershipFilter,
    WorkspaceMembershipRole,
    WorkspaceMembershipUpdate,
)

router = Router(tags=["workspace-memberships"])


@router.get("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def get_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    if user is not None and user.role < UserRole.ADMIN and user.id != user_id:
        if not await engine.workspaces.where(viewable_by=user.id).any():
            raise Failure(NotFoundError)

    return assert_found(await engine.workspace_memberships.get(user_id, workspace_id))


@router.get("/users/{user_id:uuid}/workspace-memberships", dependencies=[SELF_OR_ADMIN])
async def get_workspace_memberships(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[WorkspaceMembershipFilter, Query(), Limit(1000)],
) -> list[WorkspaceMembership]:
    return await engine.workspace_memberships.where(user_id=user_id, and__=filter)


@router.get("/workspaces/{workspace_id:uuid}/memberships")
async def get_workspace_memberships_in_workspace(
    engine: CurrentEngine,
    user: RequireViewer,
    workspace_id: UUID,
    filter: Annotated[WorkspaceMembershipFilter, Query(), Limit(1000)],
) -> list[WorkspaceMembership]:
    if user is not None and user.role < UserRole.ADMIN:
        if not await engine.workspaces.where(viewable_by=user.id).any():
            raise Failure(NotFoundError)

    return await engine.workspace_memberships.where(workspace_id=workspace_id, and__=filter)


async def _guard_membership_mutation(
    engine: CurrentEngine,
    acting_user: CurrentUser,
    membership_user_id: UUID,
    membership_workspace_id: UUID,
    assigning_workspace_role: WorkspaceMembershipRole | None,
) -> None:
    if acting_user is not None and acting_user.role < UserRole.ADMIN:
        if assigning_workspace_role is not None:
            if acting_user.id == membership_user_id:
                # The acting user owns the membership. Only allow them to change their workspace
                # role to one equal to or below their current one.
                match assigning_workspace_role:
                    case WorkspaceMembershipRole.VIEWER:
                        filter = WorkspaceFilter(viewable_by=acting_user.id)
                    case WorkspaceMembershipRole.EDITOR:
                        filter = WorkspaceFilter(editable_by=acting_user.id)
                    case WorkspaceMembershipRole.MANAGER:
                        filter = WorkspaceFilter(manageable_by=acting_user.id)
            else:
                # Otherwise, only allow managers (or admins) to change the role of other users.
                filter = WorkspaceFilter(manageable_by=acting_user.id)

            if not await engine.workspaces.where(id=membership_workspace_id, and__=filter).any():
                raise Failure(NotPermittedError)


class WorkspaceMembershipCreateData(DataObject):
    role: WorkspaceMembershipRole


@router.post("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def create_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
    data: WorkspaceMembershipCreateData,
) -> WorkspaceMembership:
    await _guard_membership_mutation(engine, user, user_id, workspace_id, data.role)
    return await engine.workspace_memberships.create(
        WorkspaceMembership(
            user_id=user_id,
            workspace_id=workspace_id,
            role=data.role,
        ),
    )


class WorkspaceMembershipUpdateData(TypedDict, total=False):
    role: WorkspaceMembershipRole


@router.patch("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def update_workspace_membership(
    engine: CurrentEngine,
    user: RequireViewer,
    user_id: UUID,
    workspace_id: UUID,
    assign: WorkspaceMembershipUpdate,
) -> WorkspaceMembership:
    if "role" in assign:
        await _guard_membership_mutation(engine, user, user_id, workspace_id, assign["role"])

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
