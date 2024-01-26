from typing import Annotated
from typer import Option
from ceres.config import Config
from ceres.data import PasswordStr, UsernameStr
from ceres.engine import Engine
from ceres.internal.cli.shared import CLIRouter, ConfigOption, get_database
from ceres.user import User, UserRole


router = CLIRouter(
    name="create",
    help="Create data entities.",
)


@router.command()
async def user(
    username: Annotated[UsernameStr, Option()],
    password: Annotated[PasswordStr, Option()],
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
    print(hash)
    print(
        await engine.create_user(
            User(
                username=username,
                hash=hash,
                email=email,
                role=role,
                disabled=disabled,
            )
        )
    )
