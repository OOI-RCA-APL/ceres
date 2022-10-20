from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Sequence

from sqlalchemy import select

from ..alert import Alert
from ..config import ScheduleConfig, UserConfig
from ..exceptions import ComponentNotLoadedException
from ..notifier import Notifier, NotifierContext
from ..path import NotifierPath
from ..protocols import ReferencedNotifierHandle
from .component import ComponentHandle, ComponentHandleContext
from .database.entity import AlertEntity
from .utilities import encode_timedelta, get_now


@dataclass(kw_only=True, frozen=True)
class NotifierHandleContext(ComponentHandleContext):
    path: NotifierPath
    schedule: ScheduleConfig | None
    lookback: timedelta
    users: list[UserConfig]


class NotifierHandle(
    ComponentHandle[
        NotifierHandleContext,
        Notifier,
        NotifierContext,
    ],
    ReferencedNotifierHandle,
):
    @property
    def path(self) -> NotifierPath:
        return self._context.path

    @property
    def schedule(self) -> ScheduleConfig | None:
        return self._context.schedule

    @property
    def lookback(self) -> timedelta:
        return self._context.lookback

    @property
    def users(self) -> Sequence[UserConfig]:
        return self._context.users

    def _get_component_type(self) -> type[Notifier]:  # type: ignore
        return Notifier

    def _get_component_context(self) -> NotifierContext:
        return NotifierContext(
            id=self._context.id,
            path=self._context.path,
            unit=self._context.unit,
            references=self._context.references,
        )

    async def notify(self) -> None:
        cutoff = get_now() - self.lookback

        async with self._context.database.session() as session:
            alerts = [
                Alert.create_from(entity)
                for entity in await session.scalars(
                    select(AlertEntity).where(AlertEntity.timestamp > cutoff)
                )
            ]

        self.logger.info(
            f"Sending notification with {len(alerts)} alert(s) found since {encode_timedelta(self.lookback)} ago."
        )

        await self.send(self.users, alerts)

    async def send(self, users: Sequence[UserConfig], alerts: list[Alert]) -> None:
        if not self._instance:
            raise ComponentNotLoadedException("Notifier is not loaded.")

        await self._instance.send(users, alerts)

    async def _tasklet_run(self) -> None:
        await super()._tasklet_run()

        if self.schedule:
            self.logger.info(f"Scheduling notifications as: {self.schedule}")
            self.scheduler.add_job(self.notify, self.schedule)
        else:
            self.logger.warning(
                "No scheduler is set. Notifications will not be sent automatically."
            )

        while True:
            await self._update()

    async def _tasklet_stop(self) -> None:
        await super()._tasklet_stop()

    async def _update(self) -> None:
        if not self._instance:
            return

        await self._instance.update()
