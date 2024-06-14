from typing import Annotated

from ceres._internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres._internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_database,
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
    async with use_database(context) as database:
        return await database.users.get(filter)


@router.command()
async def get_all(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> list[User]:
    """
    Retrieve multiple users.
    """
    async with use_database(context) as database:
        return await database.users.get_all(filter)


@router.command()
async def count(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> int:
    """
    Count users.
    """
    async with use_database(context) as database:
        return await database.users.count(filter)


@router.command()
async def create(
    *,
    data: Annotated[UserCreate, CLIOptionGroup()],
    context: CLIContext,
) -> User:
    """
    Create a new user.
    """
    async with use_database(context) as database:
        return await database.users.create(data)


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
    async with use_database(context) as database:
        return await database.users.update(filter, assign)


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
    async with use_database(context) as database:
        if confirm:
            count = await database.users.count(filter)
            get_confirmation(f"Update {count} log entries?", abort=True)

        return await database.users.update_all(filter, assign)


@router.command()
async def delete(
    *,
    filter: Annotated[CLIUserFilter, CLIOptionGroup()],
    context: CLIContext,
) -> User | None:
    """
    Delete one user. Return if found.
    """
    async with use_database(context) as database:
        return await database.users.delete(filter)


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
    async with use_database(context) as database:
        if confirm:
            count = await database.users.count(filter)
            get_confirmation(f"Delete {count} log entries?", abort=True)

        return await database.users.delete_all(filter)
