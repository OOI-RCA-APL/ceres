from __future__ import annotations

from typing import Any, override

from ceres._internal.cli.shared import CliCommand, create_entity_command, get_input
from ceres.data import PasswordHash, PasswordStr
from ceres.user import User, UserCreate


class UserCreateWithPrompt(UserCreate):
    password: PasswordStr | PasswordHash | None = None


class CreateCommand(CliCommand):
    data: UserCreateWithPrompt

    @override
    async def __run__(self) -> Any:
        data = self.data
        if data.password is None:
            data.password = get_input("Password: ", PasswordStr | PasswordHash)

        async with self.use_database() as database:
            return await database.users.create(self.data)


UsersCommand = create_entity_command(User, {"create": CreateCommand})
