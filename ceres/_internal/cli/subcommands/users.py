from __future__ import annotations

from typing import Any, override

from pydantic import field_validator
from typing_extensions import TYPE_CHECKING

from ceres._internal.cli.shared import CLICommand, create_entity_command, get_input
from ceres.data import PasswordHash, PasswordStr
from ceres.user import User, UserCreate


class PromptedUserCreate(UserCreate):
    if not TYPE_CHECKING:
        password: PasswordStr | PasswordHash | None = None

    @field_validator("password", mode="before")
    @classmethod
    def _validate_password(cls, value: Any) -> Any:
        if value is None:
            return get_input("Password", PasswordStr | PasswordHash, hidden=True)

        return value


class CreateCommand(CLICommand, PromptedUserCreate):
    @override
    async def __run__(self) -> Any:
        create = self.read(PromptedUserCreate)
        async with self.use_database() as database:
            return await database.users.create(create)


UsersCommand = create_entity_command(User, {"create": CreateCommand})
