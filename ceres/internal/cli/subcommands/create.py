from typing import Annotated

from ceres.alert import Alert
from ceres.config import Config
from ceres.data import PasswordStr, UsernameStr, jsonify
from ceres.engine import Engine
from ceres.internal.cli.plumbing import CLIOption, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import (
    ConfigOption,
    Dummy,
    get_database,
    write,
)
from ceres.logs import LogEntry
from ceres.message import Message
from ceres.user import User, UserRole

router = CLIRouter(
    name="create",
    help="Create data entities.",
)


@router.command()
async def user(
    *,
    username: Annotated[UsernameStr, CLIOption(str)],
    password: Annotated[PasswordStr, CLIOption(str, prompt=True, hide_input=True)],
    email: Annotated[str, CLIOption(str)],
    role: Annotated[UserRole, CLIOption(UserRole)] = UserRole.OPERATOR,
    disabled: Annotated[bool, CLIOption(bool)] = False,
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Create a user.
    """
    await get_database(config)
    engine = Engine(config)
    hash = await engine.hash_password(password)
    user = await engine.create_user(
        User(
            username=username,
            hash=hash,
            email=email,
            role=role,
            disabled=disabled,
        )
    )
    write(jsonify(user, indent=2))


@router.command()
async def message(
    *,
    data: Annotated[Message, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Create a message.
    """
    await get_database(config)
    engine = Engine(config)
    message = await engine.create_message(data)
    write(jsonify(message, indent=2))


@router.command()
async def alert(
    *,
    data: Annotated[Alert, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Create an alert.
    """
    await get_database(config)
    engine = Engine(config)
    alert = await engine.create_alert(data)
    write(jsonify(alert, indent=2))


@router.command()
async def log_entry(
    *,
    data: Annotated[LogEntry, CLIOptionGroup()],
    config: Annotated[Config, ConfigOption(checks=[])] = Dummy(),
) -> None:
    """
    Create a log entry.
    """
    await get_database(config)
    engine = Engine(config)
    entry = await engine.create_log_entry(data)
    write(jsonify(entry, indent=2))
