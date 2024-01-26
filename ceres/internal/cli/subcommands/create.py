from datetime import datetime
import json
from typing import TYPE_CHECKING, Annotated, Any
from uuid import UUID
from typer import Option
from ceres.config import Config
from ceres.data import PasswordStr, UsernameStr, jsonify
from ceres.engine import Engine
from ceres.internal.cli.shared import CLIRouter, ConfigOption, get_database, write
from ceres.level import Level
from ceres.message import MessageDirection
from ceres.user import User, UserRole


router = CLIRouter(
    name="create",
    help="Create data entities.",
)


@router.command()
async def user(
    *,
    username: Annotated[UsernameStr, Option()],
    password: Annotated[PasswordStr, Option(prompt=True, hide_input=True)],
    email: Annotated[str, Option()],
    role: Annotated[UserRole, Option()] = UserRole.OPERATOR,
    disabled: Annotated[bool, Option()] = False,
    config: Config = ConfigOption(checks=[]),
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
    id: Annotated[UUID | None if TYPE_CHECKING else UUID, Option()] = None,
    address: Annotated[str, Option()],
    timestamp: Annotated[datetime | None if TYPE_CHECKING else datetime, Option()] = None,
    direction: Annotated[MessageDirection, Option()],
    content: Annotated[str, Option()],
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Create a message.
    """
    await get_database(config)
    engine = Engine(config)

    data: dict[str, Any] = {}

    if id is not None:
        data["id"] = id
    data["address"] = address
    if timestamp is not None:
        data["timestamp"] = timestamp
    data["direction"] = direction
    data["content"] = content

    message = await engine.create_message(data)
    write(jsonify(message, indent=2))


@router.command()
async def alert(
    *,
    id: Annotated[UUID | None if TYPE_CHECKING else UUID, Option()] = None,
    address: Annotated[str, Option()],
    timestamp: Annotated[datetime | None if TYPE_CHECKING else datetime, Option()] = None,
    level: Annotated[Level, Option()],
    code: Annotated[str, Option()],
    info: Annotated[
        dict[str, Any] | None if TYPE_CHECKING else str, Option(parser=json.loads)
    ] = None,
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Create an alert.
    """
    await get_database(config)
    engine = Engine(config)

    data: dict[str, Any] = {}

    if id is not None:
        data["id"] = id
    data["address"] = address
    if timestamp is not None:
        data["timestamp"] = timestamp
    data["level"] = level
    data["code"] = code
    if info is not None:
        data["info"] = info

    alert = await engine.create_alert(data)
    write(jsonify(alert, indent=2))


@router.command()
async def log_entry(
    *,
    id: Annotated[UUID | None if TYPE_CHECKING else UUID, Option()] = None,
    address: Annotated[str, Option()],
    timestamp: Annotated[datetime | None if TYPE_CHECKING else datetime, Option()] = None,
    level: Annotated[Level, Option()],
    content: Annotated[str, Option()],
    config: Config = ConfigOption(checks=[]),
) -> None:
    """
    Create a log entry.
    """
    await get_database(config)
    engine = Engine(config)

    data: dict[str, Any] = {}

    if id is not None:
        data["id"] = id
    data["address"] = address
    if timestamp is not None:
        data["timestamp"] = timestamp
    data["level"] = level
    data["content"] = content

    entry = await engine.create_log_entry(data)
    write(jsonify(entry, indent=2))
