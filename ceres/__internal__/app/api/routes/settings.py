from uuid import UUID

from ceres.__internal__.app.shared import CurrentActor, CurrentEngine, CurrentUser, Router
from ceres.data import Name
from ceres.error import NotFoundError, NotPermittedError
from ceres.setting import Setting, SettingCreate

router = Router(prefix="/settings", tags=["settings"])


@router.get("/{user_id}/{name}")
async def get_setting(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: CurrentUser,
    user_id: UUID,
    name: Name,
) -> Setting:
    """Return a single setting for the given user and setting name.

    Raises:
        NotPermittedError: If the caller lacks permission.
        NotFoundError: If the setting does not exist.
    """
    if not actor.admin and (user is None or user.id != user_id):
        raise NotPermittedError()

    setting = await engine.settings.get(user_id, name)
    if setting is None:
        raise NotFoundError()

    return setting


@router.put("")
async def put_setting(
    engine: CurrentEngine,
    actor: CurrentActor,
    user: CurrentUser,
    setting: SettingCreate,
) -> Setting:
    """Create or replace a user setting via upsert.

    Raises:
        NotPermittedError: If the caller lacks permission to modify the target user's settings.
    """
    if not actor.admin and (user is None or user.id != setting.user_id):
        raise NotPermittedError()

    return await engine.settings.create(setting, upsert=True)
