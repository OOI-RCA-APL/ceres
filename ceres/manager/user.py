from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres.user import User, UserCreate, UserFilter, UserUpdate

with lazy_imports(__name__):
    from ceres._internal.auth import verify_password_hash
    from ceres.data import PasswordHash
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
    async def update_all(self, filter: UserFilter, assign: UserUpdate) -> int:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update_all(filter, assign)

    @override
    async def update(self, filter: UserFilter, assign: UserUpdate) -> User | None:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update(filter, assign)

    @override
    async def _from_create(self, data: UserCreate) -> User:
        fields = {**data.__dict__}
        fields["password"] = await self._maybe_hash_password(fields["password"])
        return User(**fields)

    async def _maybe_hash_password(self, password: str) -> PasswordHash:
        if verify_password_hash(password):
            return password

        return await self._database.hash_password(password)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = User
        _F = User.Filter
        _FA = User.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        def select(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> AsyncIterable[_E]: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...
