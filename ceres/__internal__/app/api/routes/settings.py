from uuid import UUID

from ceres.__internal__.app.shared import CurrentEngine, CurrentRole, CurrentUser, Router
from ceres.data import Name
from ceres.error import Failure, NotFoundError, NotPermittedError
from ceres.setting import Setting, SettingCreate
from ceres.user import UserRole

router = Router(prefix="/settings", tags=["settings"])


@router.get("/{user_id}/{name}")
async def get_setting(
    engine: CurrentEngine,
    role: CurrentRole,
    user: CurrentUser,
    user_id: UUID,
    name: Name,
) -> Setting:
    """Return a single setting for the given user and setting name.

    Raises:
        Failure: If the caller lacks permission or the setting does not exist.
    """
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
    """Create or replace a user setting via upsert.

    Raises:
        Failure: If the caller lacks permission to modify the target user's settings.
    """
    if role < UserRole.ADMIN and (user is None or user.id != setting.user_id):
        raise Failure(NotPermittedError())

    return await engine.settings.create(setting, upsert=True)
