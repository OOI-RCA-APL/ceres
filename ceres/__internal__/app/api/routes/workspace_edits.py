from typing import Annotated
from uuid import UUID

from fastapi import Query

from ceres.__internal__.app.shared import SELF_OR_ADMIN, CurrentEngine, Limit, Router, assert_found
from ceres.data import DataObject, JSONSerializableDict
from ceres.workspace import WorkspaceEdit, WorkspaceEditCreate, WorkspaceEditFilter

router = Router(tags=["workspace-edits"])


@router.get(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def get_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceEdit:
    """Return a single workspace edit for the given user and workspace.

    Raises:
        NotFoundError: If no matching workspace edit exists.
    """
    return assert_found(await engine.workspace_edits.get(user_id, workspace_id))


@router.get("/users/{user_id:uuid}/workspace-edits", dependencies=[SELF_OR_ADMIN])
async def get_workspace_edits(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[WorkspaceEditFilter, Query(), Limit(1000)],
) -> list[WorkspaceEdit]:
    """Return workspace edits for the given user, filtered and capped at 1000 results."""
    return await engine.workspace_edits.where(user_id=user_id, and__=filter)


class CreateWorkspaceEditData(DataObject):
    """Request body for creating a workspace edit."""

    data: JSONSerializableDict


@router.post(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def create_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
    values: CreateWorkspaceEditData,
) -> WorkspaceEdit:
    """Create a new workspace edit for the given user and workspace."""
    return await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user_id,
            workspace_id=workspace_id,
            data=values.data,
        )
    )


class AssignWorkspaceEditData(CreateWorkspaceEditData):
    """Request body for upserting a workspace edit. Identical to `CreateWorkspaceEditData`."""

    pass


@router.put(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def assign_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
    values: AssignWorkspaceEditData,
) -> WorkspaceEdit:
    """Create or replace a workspace edit for the given user and workspace via upsert."""
    return await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user_id,
            workspace_id=workspace_id,
            data=values.data,
        ),
        upsert=True,
    )


@router.delete(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def delete_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceEdit:
    """Delete a workspace edit for the given user and workspace.

    Raises:
        NotFoundError: If no matching workspace edit exists.
    """
    return assert_found(
        await engine.workspace_edits.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .delete()
        .first()
    )
