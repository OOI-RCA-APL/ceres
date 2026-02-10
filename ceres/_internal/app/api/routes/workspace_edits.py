from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from ceres._internal.app.shared import SELF_OR_ADMIN, CurrentEngine, Limit, assert_found
from ceres.data import ImmutableDataModel, JSONSerializableDict
from ceres.workspace import WorkspaceEdit, WorkspaceEditCreate, WorkspaceEditFilter

router = APIRouter(tags=["workspace-edits"])


@router.get(
    "/users/{user_id:uuid}/workspace-edits/{workspace_id:uuid}",
    dependencies=[SELF_OR_ADMIN],
)
async def get_workspace_edit(
    engine: CurrentEngine,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceEdit:
    return assert_found(await engine.workspace_edits.get(user_id, workspace_id))


@router.get("/users/{user_id:uuid}/workspace-edits", dependencies=[SELF_OR_ADMIN])
async def get_workspace_edits(
    engine: CurrentEngine,
    user_id: UUID,
    filter: Annotated[WorkspaceEditFilter, Query(), Limit(1000)],
) -> list[WorkspaceEdit]:
    return await engine.workspace_edits.where(user_id=user_id, and__=filter)


class CreateWorkspaceEditData(ImmutableDataModel):
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
    return await engine.workspace_edits.create(
        WorkspaceEditCreate(
            user_id=user_id,
            workspace_id=workspace_id,
            data=values.data,
        )
    )


class AssignWorkspaceEditData(CreateWorkspaceEditData):
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
    return assert_found(
        await engine.workspace_edits.where(
            user_id=user_id,
            workspace_id=workspace_id,
        )
        .delete()
        .first()
    )
