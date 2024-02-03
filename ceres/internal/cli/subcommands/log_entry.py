from typing import Annotated

from ceres.data import jsonify
from ceres.filter import LogEntryFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import ValidateEmptyAsNone, use_temporary_engine, write
from ceres.logs import LogEntry

router = CLIRouter(
    name="log-entry",
    help="Manage log entries.",
)


class CLILogEntryFilter(ValidateEmptyAsNone, LogEntryFilter):
    pass


@router.command()
async def select(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Retrieve alerts.
    """
    engine = await use_temporary_engine(context)
    user = await engine.get_log_entries(filter)
    write(jsonify(user, indent=2))


@router.command()
async def create(
    *,
    data: Annotated[LogEntry, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Create a log entry.
    """
    engine = await use_temporary_engine(context)
    entry = await engine.create_log_entry(data)
    write(jsonify(entry, indent=2))
