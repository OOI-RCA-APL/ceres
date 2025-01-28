from __future__ import annotations

from typing import TYPE_CHECKING, Any, AsyncIterable, Unpack, override

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.alert import Alert, AlertFilter, AlertFilterArgs
from ceres.event import AlertEvent
from ceres.level import Level
from ceres.stream import Stream

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


class AlertManager(
    BaseEntityManager[
        Alert,
        Alert.Row,
        Alert.Create,
        Alert.Update,
        Alert.Filter,
        Alert.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node, /) -> None:
        super().__init__(source, Alert)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = Alert
        _F = AlertFilter
        _FA = AlertFilterArgs

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


class BoundAlertManager(AlertManager, BaseBoundManager[Alert]):
    def __init__(self, source: Node) -> None:
        super().__init__(source)

    def store(self, alert: Alert, /) -> None:
        return self._node.store(alert)

    def follow(
        self,
        filter: AlertFilter | None = None,
        **kwargs: Unpack[AlertFilterArgs],
    ) -> Stream[Alert]:
        filter = self._apply_default_filter(filter, kwargs)
        return (
            self._node.events.follow()
            .every(AlertEvent)
            .map(lambda event: event.alert)
            .filter(filter.matches)
        )

    def emit(
        self,
        level: Level,
        code: str,
        data: dict[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            address=self._node.address,
            level=level,
            type=code,
            data=data if data is not None else {},
        )

        self._node.store(alert)
        self._node.events.emit(AlertEvent, alert=alert)
        return alert

    def debug(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        return self.emit(Level.DEBUG, type, data)

    def info(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        return self.emit(Level.INFO, type, data)

    def warning(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        return self.emit(Level.WARNING, type, data)

    def error(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        return self.emit(Level.ERROR, type, data)

    def critical(self, type: str, data: dict[str, Any] | None = None) -> Alert:
        return self.emit(Level.CRITICAL, type, data)
