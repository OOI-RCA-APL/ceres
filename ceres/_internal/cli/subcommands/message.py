from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)
from ceres.message import Message, MessageFilter, MessageUpdate

router = CLIRouter(
    name="message",
    help="Manage messages.",
)


class CLIMessageFilter(ValidateEmptyAsNone, MessageFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Message | None:
    """
    Retrieve one message.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[Message]:
    """
    Retrieve multiple messages.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count messages.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[Message, CLIOptionGroup()],
    context: CLIContext,
) -> Message:
    """
    Create a new message.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    assign: Assign[MessageUpdate],
    context: CLIContext,
) -> Message | None:
    """
    Update one message. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    assign: Assign[MessageUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple messages. Return the number updated.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.messages.count(filter)
        get_confirmation(f"Update {count} messages?", abort=True)

    return await engine.messages.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    context: CLIContext,
) -> Message | None:
    """
    Delete one message. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.messages.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLIMessageFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple messages. Return the number deleted.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.messages.count(filter)
        get_confirmation(f"Delete {count} messages?", abort=True)

    return await engine.messages.delete_all(filter)
