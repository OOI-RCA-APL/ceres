from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_database,
)
from ceres.alert import Alert, AlertFilter, AlertUpdate

router = CLIRouter(
    name="alerts",
    help="Manage alerts.",
)


class CLIAlertFilter(AlertFilter, ValidateEmptyAsNone):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Alert | None:
    """
    Retrieve one alert.
    """
    async with use_database(context) as database:
        return await database.alerts.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Alert]:
    """
    Retrieve multiple alerts.
    """
    async with use_database(context) as database:
        return await database.alerts.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count alerts.
    """
    async with use_database(context) as database:
        return await database.alerts.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[Alert, CLIOptionGroup()],
    context: CLIContext,
) -> Alert:
    """
    Create an alert.
    """
    async with use_database(context) as database:
        return await database.alerts.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    assign: Assign[AlertUpdate],
    context: CLIContext,
) -> Alert | None:
    """
    Update an alert. Return if found.
    """
    async with use_database(context) as database:
        return await database.alerts.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    assign: Assign[AlertUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple alerts. Return the number updated.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.alerts.count(filter)
            get_confirmation(f"Update {count} alerts?", abort=True)

        return await database.alerts.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Delete an alert.
    """
    async with use_database(context) as database:
        await database.alerts.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple alerts. Return the number deleted.
    """
    async with use_database(context) as database:
        if confirm:
            count = await database.alerts.count(filter)
            get_confirmation(f"Delete {count} alerts?", abort=True)

        return await database.alerts.delete_all(filter)
