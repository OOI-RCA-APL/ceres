from typing import Annotated

from ceres.config import Config
from ceres.data import jsonify
from ceres.engine import Engine
from ceres.internal.cli.filter import (
    CLIAlertFilter,
    CLILogEntryFilter,
    CLIMessageFilter,
    CLIUserFilter,
)
from ceres.internal.cli.plumbing import CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import ConfigOption, Dummy, get_database, write

router = CLIRouter(
    name="get",
    help="Retrieve data entities.",
)


@router.command()
async def users(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Retrieve users.
    """
    await get_database(config)
    engine = Engine(config)
    user = await engine.get_users(filter)
    write(jsonify(user, indent=2))


@router.command()
async def messages(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Retrieve messages.
    """
    await get_database(config)
    engine = Engine(config)
    user = await engine.get_messages(filter)
    write(jsonify(user, indent=2))


@router.command()
async def alerts(
    *,
    filter: Annotated[CLIAlertFilter, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Retrieve alerts.
    """
    await get_database(config)
    engine = Engine(config)
    user = await engine.get_alerts(filter)
    write(jsonify(user, indent=2))


@router.command()
async def log_entries(
    *,
    filter: Annotated[CLILogEntryFilter, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Retrieve alerts.
    """
    await get_database(config)
    engine = Engine(config)
    user = await engine.get_log_entries(filter)
    write(jsonify(user, indent=2))
