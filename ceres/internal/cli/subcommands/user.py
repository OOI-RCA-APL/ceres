from typing import Annotated

from ceres.data import PasswordHash, jsonify
from ceres.filter import UserFilter
from ceres.internal.cli.plumbing import CLIContext, CLIOptionGroup, CLIRouter
from ceres.internal.cli.shared import ValidateEmptyAsNone, use_temporary_engine, write
from ceres.user import User, UserCreate

router = CLIRouter(
    name="user",
    help="Manage users.",
)


class CLIUserFilter(ValidateEmptyAsNone, UserFilter):
    pass


@router.command()
async def select(
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
async def create(
    *,
    data: Annotated[UserCreate, CLIOptionGroup()],
    context: CLIContext,
) -> None:
    """
    Create a user.
    """
    engine = await use_temporary_engine(context)
    hash = (
        PasswordHash(data.password)
        if data.password_is_hashed
        else await engine.hash_password(data.password)
    )

    values = data.model_dump(exclude={"password_is_hashed"})
    values["password"] = hash
    user = await engine.create_user(User(**values))
    write(jsonify(user, indent=2))
