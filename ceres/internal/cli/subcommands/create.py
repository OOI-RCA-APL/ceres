from typing import Annotated

from ceres.alert import Alert
from ceres.data import PasswordStr, UsernameStr, jsonify
from ceres.internal.cli.plumbing import CLIContext, CLIOption, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import (
    use_temporary_engine,
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
    context: CLIContext,
) -> None:
    """
    Create a user.
    """
    engine = await use_temporary_engine(context)
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
    context: CLIContext,
) -> None:
    """
    Create a message.
    """
    engine = await use_temporary_engine(context)
    message = await engine.create_message(data)
    write(jsonify(message, indent=2))


@router.command()
async def alert(
    *,
    data: Annotated[Alert, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Create an alert.
    """
    engine = await use_temporary_engine(context)
    alert = await engine.create_alert(data)
    write(jsonify(alert, indent=2))


@router.command()
async def log_entry(
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
