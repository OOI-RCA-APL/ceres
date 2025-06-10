from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter
from pydantic import Field

from ceres._internal.app.shared import CurrentEngine, CurrentRole, CurrentUser
from ceres.data import Name
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.setting import Setting, SettingCreate, SettingFilter
from ceres.user import UserRole

router = APIRouter(prefix="/settings", tags=["settings"])


class GetSettingsQueryParameters(SettingFilter):
    limit: int = Field(default=100, ge=0, le=1000)


@router.get("/{user_id}/{name}")
async def get_setting(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    user_id: UUID,
    name: Name,
) -> Setting:
    if role < UserRole.ADMIN and (user is None or user.id != user_id):
        raise Failure(NotPermittedError)

    setting = await engine.settings.get(user_id, name)
    if setting is None:
        raise Failure(NotFoundError)

    return setting


@router.put("")
async def put_setting(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    setting: SettingCreate,
) -> Setting:
    if role < UserRole.ADMIN and (user is None or user.id != setting.user_id):
        raise Failure(NotPermittedError())

    return await engine.settings.create(setting, upsert=True)
