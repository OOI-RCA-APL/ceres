from __future__ import annotations

from typing import TYPE_CHECKING, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres.user import User

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


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
    def __init__(self, source: Database | Node) -> None:
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

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = User

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> _E | None: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _E.Filter | None = None, **kwargs: Unpack[_E.FilterArgs]
        ) -> int: ...
