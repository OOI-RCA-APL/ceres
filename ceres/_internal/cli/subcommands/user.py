from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)
from ceres.user import User, UserCreate, UserFilter, UserUpdate

router = CLIRouter(
    name="user",
    help="Manage users.",
)


class CLIUserFilter(ValidateEmptyAsNone, UserFilter):
    pass


@router.command()
async def get(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> User | None:
    """
    Retrieve one user.
    """
    engine = await use_temporary_engine(context)
    user = await engine.users.get(filter)
    return user


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[User]:
    """
    Retrieve multiple users.
    """
    engine = await use_temporary_engine(context)
    return await engine.users.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count users.
    """
    engine = await use_temporary_engine(context)
    return await engine.users.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[UserCreate, CLIOptionGroup()],
    context: CLIContext,
) -> User:
    """
    Create a new user.
    """
    engine = await use_temporary_engine(context)
    return await engine.users.create(data)


@router.command()
async def update(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    assign: Assign[UserUpdate],
    context: CLIContext,
) -> User | None:
    """
    Update one user. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.users.update(filter, assign)


@router.command()
async def update_all(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    assign: Assign[UserUpdate],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Update multiple users. Return the number updated.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.users.count(filter)
        get_confirmation(f"Update {count} log entries?", abort=True)

    return await engine.users.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> User | None:
    """
    Delete one user. Return if found.
    """
    engine = await use_temporary_engine(context)
    return await engine.users.delete(filter)


@router.command()
async def delete_all(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    confirm: Confirm = True,
    context: CLIContext,
) -> int:
    """
    Delete multiple users. Return the number deleted.
    """
    engine = await use_temporary_engine(context)
    if confirm:
        count = await engine.users.count(filter)
        get_confirmation(f"Delete {count} log entries?", abort=True)

    return await engine.users.delete_all(filter)
