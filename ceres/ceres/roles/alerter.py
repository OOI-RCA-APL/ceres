from typing import Any, Mapping

from ceres.alert import Alert
from ceres.component import Component
from ceres.events import AlertEvent
from ceres.level import Level


class Alerter(Component):
    def alert(
        self,
        level: Level,
        code: str,
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        alert = Alert(
            source=self.address,
            level=level,
            code=code,
            info=info if info is not None else {},
        )
        self.emit(AlertEvent, alert=alert)
        return alert
