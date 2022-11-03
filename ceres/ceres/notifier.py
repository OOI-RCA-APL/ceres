import asyncio
from abc import abstractmethod
from dataclasses import field
from datetime import timedelta
from typing import Any, Sequence

from pydantic import Field, validator
from sqlalchemy import select

from .alert import Alert
from .component import Component, ComponentContext, ComponentParameters
from .config import UserConfig
from .internal.database.entity import AlertEntity
from .internal.database.manager import DatabaseManager
from .internal.utilities import encode_td, frozenlist, validate_positive_timedelta
from .schedule import Schedule
from .utilities import utc, vdc


@vdc(frozen=True)
class NotifierParameters(ComponentParameters):
    schedule: Schedule | None = Field(default=None, discriminator="kind")
    lookback: timedelta

    @validator("lookback", pre=True)
    def _validate_lookback(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@vdc(frozen=True)
class NotifierContext(ComponentContext):
    users: frozenlist[UserConfig] = field(default_factory=frozenlist)
    database: DatabaseManager


class Notifier(Component):
    parameters: NotifierParameters
    context: NotifierContext

    @abstractmethod
    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        ...

    async def notify(self) -> None:
        users = self.context.users
        lookback = self.parameters.lookback
        database = self.context.database
        cutoff = utc() - lookback

        async with database.session() as session:
            alerts = [
                Alert.create_from(entity)
                for entity in await session.scalars(
                    select(AlertEntity).where(AlertEntity.timestamp > cutoff)
                )
            ]

        if not alerts:
            self.logger.info(
                f"No alerts were reported in the last {encode_td(lookback)}. Notifications will not be sent."
            )
            return

        self.logger.info(
            f"{len(alerts)} alert(s) were reported in the last {encode_td(lookback)}...",
        )

        if not users:
            self.logger.warning("No users exist to send notifications to.")
            return

        await self.send(self.context.users, alerts)

    async def _tasklet_run(self) -> None:
        await super()._tasklet_run()

        if self.parameters.schedule:
            self.logger.info(f"Scheduling notifications as: {self.parameters.schedule}")
            self.scheduler.add_job(self.notify, self.parameters.schedule)
        else:
            self.logger.warning(
                "No scheduler is set. Notifications will not be sent automatically."
            )

        while True:
            await asyncio.sleep(1)
