import logging
from asyncio import sleep

from ceres.alert import Alert, AlertLevel
from ceres.component import Component
from ceres.data import jsonify
from ceres.events import AlertEmittedEvent
from ceres.internal.database.buffer import WriteBuffer
from ceres.internal.database.entities import AlertEntity
from ceres.routine import routine


class Alerter(Component):
    def __setup__(self) -> None:
        super().__setup__()
        self.__alert_write_buffer = WriteBuffer(
            Alert,
            AlertEntity,
            lambda: self.environment,
            self.logger,
        )

    async def __stop__(self) -> None:
        await self.__alert_write_buffer.flush()
        await super().__stop__()

    @routine
    async def __flush_alert_buffer(self) -> None:
        while True:
            await self.__alert_write_buffer.flush()
            await sleep(0.1)

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
