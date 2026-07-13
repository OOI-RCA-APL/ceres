from typing import Annotated, TypedDict
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import (
    SELF_OR_ADMIN,
    CurrentEngine,
    CurrentUser,
    Limit,
    RequireAuthenticated,
    Router,
    assert_found,
)
from ceres.data import DataObject
from ceres.error import NotFoundError, NotPermittedError
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
    user: RequireAuthenticated,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    """Return a workspace membership for the given user and workspace.

    Non-admin callers can only view their own memberships or memberships in workspaces they can
    view.

    Raises:
        NotFoundError: If the caller lacks access or the membership does not exist.
    """
    if user is not None and not user.admin and user.id != user_id:
        if not await engine.workspaces.where(viewable_by=user.id).any():
            raise NotFoundError()

    return assert_found(await engine.workspace_memberships.get(user_id, workspace_id))


@router.get("/users/{user_id:uuid}/workspace-memberships", dependencies=[SELF_OR_ADMIN])
async def get_workspace_memberships(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[WorkspaceMembershipFilter, Query(), Limit(1000)],
) -> list[WorkspaceMembership]:
    """Return workspace memberships for a user, filtered and capped at 1000 results."""
    return await engine.workspace_memberships.where(user_id=user_id, and__=filter)


@router.get("/workspaces/{workspace_id:uuid}/memberships")
async def get_workspace_memberships_in_workspace(
    engine: CurrentEngine,
    user: RequireAuthenticated,
    workspace_id: UUID,
    filter: Annotated[WorkspaceMembershipFilter, Query(), Limit(1000)],
) -> list[WorkspaceMembership]:
    """Return all memberships within a workspace. Non-admin callers must have view access.

    Raises:
        NotFoundError: If the caller lacks view access to the workspace.
    """
    if user is not None and not user.admin:
        if not await engine.workspaces.where(viewable_by=user.id).any():
            raise NotFoundError()

    return await engine.workspace_memberships.where(workspace_id=workspace_id, and__=filter)


async def _guard_membership_mutation(
    engine: CurrentEngine,
    acting_user: CurrentUser,
    membership_user_id: UUID,
    membership_workspace_id: UUID,
    assigning_workspace_role: WorkspaceMembershipRole | None,
) -> None:
    """Verify the acting user has permission to create or change a workspace membership.

    For non-admin callers, the rules depend on whether the caller owns the membership and on
    the workspace role being assigned. Managers may change other users' roles, but regular
    users can only lower their own.

    Args:
        engine: The current engine instance.
        acting_user: The user making the request, or ``None`` if authentication is disabled.
        membership_user_id: The user ID of the membership being mutated.
        membership_workspace_id: The workspace ID of the membership being mutated.
        assigning_workspace_role: The workspace role being assigned, or ``None`` if the role
            is not being changed.

    Raises:
        NotPermittedError: If the acting user lacks the required workspace-level permission.
    """
    if acting_user is not None and not acting_user.admin:
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
                raise NotPermittedError()


class WorkspaceMembershipCreateData(DataObject):
    """Request body for creating a workspace membership."""

    role: WorkspaceMembershipRole


@router.post("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def create_workspace_membership(
    engine: CurrentEngine,
    user: RequireAuthenticated,
    user_id: UUID,
    workspace_id: UUID,
    data: WorkspaceMembershipCreateData,
) -> WorkspaceMembership:
    """Create a workspace membership for the given user and workspace.

    Raises:
        NotPermittedError: If the caller lacks permission for the requested role.
    """
    await _guard_membership_mutation(engine, user, user_id, workspace_id, data.role)
    return await engine.workspace_memberships.create(
        WorkspaceMembership(
            user_id=user_id,
            workspace_id=workspace_id,
            role=data.role,
        ),
    )


class WorkspaceMembershipUpdateData(TypedDict, total=False):
    """Request body for updating a workspace membership."""

    role: WorkspaceMembershipRole


@router.patch("/users/{user_id:uuid}/workspace-memberships/{workspace_id:uuid}")
async def update_workspace_membership(
    engine: CurrentEngine,
    user: RequireAuthenticated,
    user_id: UUID,
    workspace_id: UUID,
    assign: WorkspaceMembershipUpdate,
) -> WorkspaceMembership:
    """Partially update a workspace membership (currently only the role field).

    Raises:
        NotPermittedError: If the caller lacks permission.
        NotFoundError: If the membership does not exist.
    """
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
    user: RequireAuthenticated,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    """Delete a workspace membership. Non-admin callers who are not the membership owner must be
    at least an editor in the workspace.

    Raises:
        NotPermittedError: If the caller lacks permission.
        NotFoundError: If the membership does not exist.
    """
    if user is not None and not user.admin and user.id != user_id:
        # Only editors or admins can delete memberships for other users.
        membership = await engine.workspace_memberships.get(user.id, workspace_id)
        if membership is None or membership.role < WorkspaceMembershipRole.EDITOR:
            raise NotPermittedError()

    return assert_found(
        await engine.workspace_memberships.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .delete()
        .first()
    )
