import asyncio
from abc import ABC
from dataclasses import field
from datetime import timedelta
from typing import Any, Sequence

from pydantic import Field, validator
from pydantic.dataclasses import dataclass as validated_dataclass
from sqlalchemy import select

from .alert import Alert
from .component import Component, ComponentContext, ComponentParameters
from .config import UserConfig
from .internal.database.entity import AlertEntity
from .internal.database.manager import DatabaseManager
from .internal.utilities import (
    encode_td,
    frozenlist,
    get_now,
    validate_positive_timedelta,
)
from .path import LocalNotifierPath, NotifierPath
from .protocols import ReferencedNotifierHandle
from .reference import Reference
from .schedule import Schedule


@validated_dataclass(kw_only=True, frozen=True)
class NotifierParameters(ComponentParameters):
    schedule: Schedule | None = Field(default=None, discriminator="kind")
    lookback: timedelta

    @validator("lookback", pre=True)
    def _validate_lookback(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@validated_dataclass(kw_only=True, frozen=True)
class NotifierContext(ComponentContext):
    path: NotifierPath
    users: frozenlist[UserConfig] = field(default_factory=frozenlist)
    database: DatabaseManager


class Notifier(Component[NotifierParameters, NotifierContext], ABC):
    def __init__(
        self,
        parameters: NotifierParameters,
        context: NotifierContext,
    ) -> None:
        super().__init__(parameters, context)

    async def send(self, users: Sequence[UserConfig], alerts: Sequence[Alert]) -> None:
        raise NotImplementedError()

    async def notify(self) -> None:
        users = self.context.users
        lookback = self.parameters.lookback
        database = self.context.database
        cutoff = get_now() - lookback

        async with database.session() as session:
            alerts = [
                Alert.create_from(entity)
                for entity in await session.scalars(
                    select(AlertEntity).where(AlertEntity.timestamp > cutoff)
                )
            ]

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


class NotifierReference(Reference[ReferencedNotifierHandle]):
    @property
    def path(self) -> LocalNotifierPath:
        return LocalNotifierPath(self.name)
