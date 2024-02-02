from typing import Annotated

from ceres.data import jsonify
from ceres.internal.cli.filter import (
    CLIAlertFilter,
    CLILogEntryFilter,
    CLIMessageFilter,
    CLIUserFilter,
)
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import use_temporary_engine, write

router = CLIRouter(
    name="get",
    help="Retrieve data entities.",
)


@router.command()
async def users(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Retrieve users.
    """
    engine = await use_temporary_engine(context)
    user = await engine.get_users(filter)
    write(jsonify(user, indent=2))


@router.command()
async def messages(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Retrieve messages.
    """
    engine = await use_temporary_engine(context)
    user = await engine.get_messages(filter)
    write(jsonify(user, indent=2))


@router.command()
async def alerts(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Retrieve alerts.
    """
    engine = await use_temporary_engine(context)
    user = await engine.get_alerts(filter)
    write(jsonify(user, indent=2))


@router.command()
async def log_entries(
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
