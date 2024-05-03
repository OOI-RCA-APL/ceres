from typing_extensions import override

from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.typedecs import __Database__, __Node__
from ceres.user import User


class UserManager(
    BaseEntityManager[
        User,
        User.Row,
        User.Create,
        User.Update,
        User.Filter,
        User.FilterArgs,
    ]
):
    def __init__(self, source: __Database__ | __Node__) -> None:
        super().__init__(source, User)

    @override
    async def update_all(self, filter: User.Filter, assign: User.Update) -> int:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update_all(filter, assign)

    @override
    async def update(self, filter: User.Filter, assign: User.Update) -> User | None:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update(filter, assign)

    @override
    async def _from_create(self, data: User.Create) -> User:
        fields = {**data.__dict__}
        fields["password"] = await self._maybe_hash_password(fields["password"])
        return User(**fields)
