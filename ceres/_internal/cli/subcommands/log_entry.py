from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)
from ceres.logs import LogEntry, LogEntryFilter, LogEntryUpdate

router = CLIRouter(
    name="log-entry",
    help="Manage log entries.",
)


class CLILogEntryFilter(ValidateEmptyAsNone, LogEntryFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> LogEntry | None:
    """
    Retrieve one log entry.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[LogEntry]:
    """
    Retrieve multiple alerts.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count log entries.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[LogEntry, CLIOptionGroup()],
    context: CLIContext,
) -> LogEntry:
    """
    Create a log entry.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    assign: Assign[LogEntryUpdate],
    context: CLIContext,
) -> LogEntry | None:
    """
    Update one log entry. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    assign: Assign[LogEntryUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple log entries. Return the number updated.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.log.count(filter)
        get_confirmation(f"Update {count} log entries?", abort=True)

    return await engine.log.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> LogEntry | None:
    """
    Delete one log entry. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.log.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple log entries. Return the number deleted.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.log.count(filter)
        get_confirmation(f"Delete {count} log entries?", abort=True)

    return await engine.log.delete_all(filter)
