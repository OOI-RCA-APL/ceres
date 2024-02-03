from typing import Annotated

from ceres.data import jsonify
from ceres.filter import MessageFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import ValidateEmptyAsNone, use_temporary_engine, write
from ceres.message import Message

router = CLIRouter(
    name="messages",
    help="Manage messages.",
)


class CLIMessageFilter(ValidateEmptyAsNone, MessageFilter):
    pass


@router.command()
async def select(
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
async def create(
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
