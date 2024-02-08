from typing import Annotated

from ceres.alert import Alert, AlertUpdate
from ceres.filter import AlertFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)

router = CLIRouter(
    name="alert",
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
    engine = await use_temporary_engine(context)
    return await engine.get_alert(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Alert]:
    """
    Retrieve multiple alerts.
    """
    engine = await use_temporary_engine(context)
    return await engine.get_alerts(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count alerts.
    """
    engine = await use_temporary_engine(context)
    return await engine.count_alerts(filter)


@router.command()
async def create(
    *,
    data: Annotated[Alert, CLIOptionGroup()],
    context: CLIContext,
) -> Alert:
    """
    Create an alert.
    """
    engine = await use_temporary_engine(context)
    return await engine.create_alert(data)


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
    engine = await use_temporary_engine(context)
    return await engine.update_alert(filter, assign)


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
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.count_alerts(filter)
        get_confirmation(f"Update {count} alerts?", abort=True)

    return await engine.update_alerts(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Delete an alert.
    """
    engine = await use_temporary_engine(context)
    await engine.delete_alert(filter)


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
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.count_alerts(filter)
        get_confirmation(f"Delete {count} alerts?", abort=True)

    return await engine.delete_alerts(filter)
