from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentRole, CurrentUser
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.setting import Setting, SettingCreate
from ceres.user import UserRole
from ceres.workspace import WorkspaceMembership, WorkspaceMembershipFilter

router = APIRouter(prefix="/workspace-memberships", tags=["workspace-memberships"])


class GetWorkspaceMembershipsQueryParameters(WorkspaceMembershipFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get("/{user_id:uuid}/{workspace_id:uuid}")
async def get_workspace_membership(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    user_id: UUID,
    workspace_id: UUID,
) -> WorkspaceMembership:
    if role < UserRole.ADMIN and (user is None or user.id != user_id):
        raise Failure(NotPermittedError)

    membership = await engine.workspace_memberships.get(user_id, workspace_id)
    if membership is None:
        raise Failure(NotFoundError)

    return membership


@router.put("")
async def put_setting(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    setting: SettingCreate,
) -> Setting:
    if role < UserRole.ADMIN and (user is None or user.id != setting.user_id):
        raise Failure(NotPermittedError())

    return await engine.settings.create(
        setting,
        upsert_on=[Setting.Row.user_id, Setting.Row.name],
    )
