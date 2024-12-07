from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_database,
)
from ceres.setting import Setting, SettingFilter, SettingUpdate

router = CLIRouter(
    name="settings",
    help="Manage user settings.",
)


class CLISettingFilter(ValidateEmptyAsNone, SettingFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Setting | None:
    """
    Retrieve one setting.
    """
    async with use_database(context) as database:
        return await database.settings.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Setting]:
    """
    Retrieve multiple settings.
    """
    async with use_database(context) as database:
        return await database.settings.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count settings.
    """
    async with use_database(context) as database:
        return await database.settings.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[Setting, CLIOptionGroup()],
    context: CLIContext,
) -> Setting:
    """
    Create a new setting.
    """
    async with use_database(context) as database:
        return await database.settings.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    assign: Assign[SettingUpdate],
    context: CLIContext,
) -> Setting | None:
    """
    Update one setting. Return if found.
    """
    async with use_database(context) as database:
        return await database.settings.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    assign: Assign[SettingUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple settings. Return the number updated.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.settings.count(filter)
            get_confirmation(f"Update {count} settings?", abort=True)

        return await database.settings.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Setting | None:
    """
    Delete one setting. Return if found.
    """
    async with use_database(context) as database:
        return await database.settings.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLISettingFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple settings. Return the number deleted.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.settings.count(filter)
            get_confirmation(f"Delete {count} settings?", abort=True)

        return await database.settings.delete_all(filter)
