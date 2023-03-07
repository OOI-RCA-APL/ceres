import logging

from ceres.alert import Alert, AlertLevel
from ceres.component import Component
from ceres.data import jsonify
from ceres.events import AlertEmittedEvent


class Alerter(Component):
    def emit_alert(self, alert: Alert) -> Alert:
        match alert.level:
            case AlertLevel.DEBUG:
                log_level = logging.DEBUG
            case AlertLevel.INFO:
                log_level = logging.INFO
            case AlertLevel.WARNING:
                log_level = logging.WARNING
            case AlertLevel.ERROR:
                log_level = logging.ERROR
            case AlertLevel.CRITICAL:
                log_level = logging.CRITICAL

        self.emit_event(AlertEmittedEvent(alert=alert))
        self.logger.log(log_level, f"Alert: {jsonify(alert)}")
        return alert
