from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterable, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres.setting import Setting

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


class SettingManager(
    BaseEntityManager[
        Setting,
        Setting.Row,
        Setting.Create,
        Setting.Update,
        Setting.Filter,
        Setting.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node, /) -> None:
        super().__init__(source, Setting)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Setting
        _F = Setting.Filter
        _FA = Setting.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
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
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, /, **kwargs: Unpack[_FA]
        ) -> int: ...
