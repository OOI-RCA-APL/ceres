from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentRole, CurrentUser
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.user import UserRole
from ceres.workspace import Workspace, WorkspaceFilter

router = APIRouter(prefix="/workspace-memberships", tags=["workspace-memberships"])


class GetWorkspaceQueryParameters(WorkspaceFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get("/{id:uuid}")
async def get_workspace(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    id: UUID,
) -> Workspace:
    if role < UserRole.ADMIN and user is None:
        raise Failure(NotPermittedError)

    scoped = WorkspaceFilter(id=id)
    if user is not None:
        scoped &= WorkspaceFilter(viewable_by=user.id)

    workspace = await engine.workspaces.where(scoped).first()
    if workspace is None:
        raise Failure(NotFoundError)

    return workspace


@router.get("")
async def get_workspaces(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    filter: Annotated[GetWorkspaceQueryParameters, Query()],
) -> list[Workspace]:
    if role < UserRole.ADMIN and user is None:
        raise Failure(NotPermittedError)

    scoped = WorkspaceFilter.model_validate(filter, from_attributes=True)
    if user is not None:
        scoped &= WorkspaceFilter(viewable_by=user.id)

    return await engine.workspaces.where(scoped)
