from typing import Annotated

from ceres.data import PasswordHash
from ceres.filter import UserFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import (
    Assign,
    Confirm,
    ValidateEmptyAsNone,
    get_confirmation,
    use_temporary_engine,
)
from ceres.user import User, UserCreate, UserUpdate

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
    user = await engine.get_user(filter)
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
    return await engine.get_users(filter)


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
    return await engine.count_users(filter)


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
    hash = (
        PasswordHash(data.password)
        if data.password_is_hashed
        else await engine.hash_password(data.password)
    )

    values = data.model_dump(exclude={"password_is_hashed"})
    values["password"] = hash
    return await engine.create_user(User(**values))


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
    return await engine.update_user(filter, assign)


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
        count = await engine.count_users(filter)
        get_confirmation(f"Update {count} log entries?", abort=True)

    return await engine.update_users(filter, assign)


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
    return await engine.delete_user(filter)


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
        count = await engine.count_users(filter)
        get_confirmation(f"Delete {count} log entries?", abort=True)

    return await engine.delete_users(filter)
