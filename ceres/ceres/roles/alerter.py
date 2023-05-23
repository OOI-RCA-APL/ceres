from typing import Any, Mapping

from ceres.alert import Alert
from ceres.component import Component
from ceres.events import AlertEmittedEvent
from ceres.level import Level


class Alerter(Component):
    def emit_alert(
        self,
        level: Level,
        code: str,
        info: Mapping[str, Any] | None = None,
    ) -> Alert:
        return self.emit_alert_instance(
            Alert(
                source=self.address,
                level=level,
                code=code,
                info=info if info is not None else {},
            )
        )

    def emit_alert_instance(self, alert: Alert) -> Alert:
        self.emit_event(AlertEmittedEvent, alert=alert)
        return alert
