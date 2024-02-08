from typing import Annotated

from ceres.filter import LogEntryFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)
from ceres.logs import LogEntry, LogEntryUpdate

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
    return await engine.get_log_entry(filter)


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
    return await engine.get_log_entries(filter)


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
    return await engine.count_log_entries(filter)


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
    return await engine.create_log_entry(data)


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
    return await engine.update_log_entry(filter, assign)


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
        count = await engine.count_log_entries(filter)
        get_confirmation(f"Update {count} log entries?", abort=True)

    return await engine.update_log_entries(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Delete log entries. Return the number deleted.
    """
    engine = await use_temporary_engine(context)
    return await engine.delete_log_entries(filter)


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
        count = await engine.count_log_entries(filter)
        get_confirmation(f"Delete {count} log entries?", abort=True)

    return await engine.delete_log_entries(filter)
