from typing import TYPE_CHECKING, Any, override

from pydantic import field_validator

from ceres.__internal__.cli.shared import CLICommand, create_entity_command, get_input
from ceres.data import Password, PasswordHash
from ceres.user import User, UserCreate


class PromptedUserCreate(UserCreate):
    """Variant of `UserCreate` that interactively prompts for the password when not provided."""

    if not TYPE_CHECKING:
        password: Password | PasswordHash | None = None

    @field_validator("password", mode="before")
    @classmethod
    def _validate_password(cls, value: Any) -> Any:
        """Prompt the user for a password if none was provided."""
        if value is None:
            return get_input("Password", Password | PasswordHash, hidden=True)

        return value


class CreateCommand(CLICommand, PromptedUserCreate.Model):
    """Create a new user, prompting for a password if not supplied."""

    @override
    async def __run__(self) -> None:
        """Read user creation data from command fields and insert the user into the database."""
        create = self.read(PromptedUserCreate)
        async with self.use_database() as database:
            await self.put(await database.users.create(create))


UsersCommand = create_entity_command(User, {"create": CreateCommand})
