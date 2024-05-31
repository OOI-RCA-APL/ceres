from __future__ import annotations

from typing import Any, Mapping

from typing_extensions import Unpack

from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.entity import BaseEntityManager
from ceres._internal.manager.manager import BaseBoundManager
from ceres.alert import Alert, AlertFilter, AlertFilterArgs
from ceres.event import AlertEvent
from ceres.level import Level
from ceres.stream import Stream

with lazy_imports(__name__):
    from ceres.database.database import Database
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
    def __init__(self, source: Database | Node) -> None:
        super().__init__(source, Alert)


class LiveAlertManager(AlertManager, BaseBoundManager[Alert]):
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
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            address=self._node.address,
            level=level,
            code=code,
            info=dict(info) if info is not None else {},
        )

        self._node.store(alert)
        self._node.events.emit(AlertEvent, alert=alert)
        return alert

    def debug(self, code: str, info: Mapping[str, Any] | None = None) -> Alert:
        return self.emit(Level.DEBUG, code, info)

    def info(self, code: str, info: Mapping[str, Any] | None = None) -> Alert:
        return self.emit(Level.INFO, code, info)

    def warning(self, code: str, info: Mapping[str, Any] | None = None) -> Alert:
        return self.emit(Level.WARNING, code, info)

    def error(self, code: str, info: Mapping[str, Any] | None = None) -> Alert:
        return self.emit(Level.ERROR, code, info)

    def critical(self, code: str, info: Mapping[str, Any] | None = None) -> Alert:
        return self.emit(Level.CRITICAL, code, info)
