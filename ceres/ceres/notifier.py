from abc import abstractmethod
from datetime import timedelta
from typing import Any, Sequence

from pydantic import Field, validator

from .alert import Alert
from .component import Component
from .internal.database.entity import EntityManager
from .internal.utilities import encode_td, validate_positive_timedelta
from .schedule import Schedule
from .utilities import utc


class Notifier(Component):
    class Parameters(Component.Parameters):
        schedule: Schedule | None = Field(default=None, discriminator="kind")
        lookback: timedelta

        @validator("lookback", pre=True)
        def _validate_lookback(cls, value: Any) -> timedelta:
            return validate_positive_timedelta(value)

    class Context(Component.Context):
        entities: EntityManager

    parameters: Parameters
    context: Context

    @abstractmethod
    async def send(self, alerts: Sequence[Alert]) -> None:
        ...

    async def notify(self) -> None:
        cutoff = utc() - self.parameters.lookback

        alerts = await self.context.entities.get_alerts(
            where=lambda alert: alert.timestamp > cutoff
        )

        if not alerts:
            self.logger.info(
                f"No alerts were reported in the last {encode_td(self.parameters.lookback)}. Notifications will not be sent."
            )
            return

        self.logger.info(
            f"{len(alerts)} alert(s) were reported in the last {encode_td(self.parameters.lookback)}.",
        )

        self.logger.info("Sending notifications...")
        await self.send(alerts)

    async def __run__(self) -> None:
        if self.parameters.schedule:
            self.logger.info(f"Scheduling notifications as: {self.parameters.schedule}")
            self.scheduler.add_job(self.notify, self.parameters.schedule)
        else:
            self.logger.warning(
                "No scheduler is set. Notifications will not be sent automatically."
            )

        await super().__run__()
