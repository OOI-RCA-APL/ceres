from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import select

from ..alert import Alert
from ..config import NotifierConfig, UserConfig
from ..exceptions import ComponentNotLoadedException
from ..notifier import Notifier, NotifierContext
from ..path import NotifierPath
from ..protocols import ReferencedNotifierHandle
from .component import ComponentHandle, ComponentHandleContext
from .database.entity import AlertEntity
from .utilities import encode_td, get_now


@dataclass(kw_only=True, frozen=True)
class NotifierHandleContext(ComponentHandleContext):
    path: NotifierPath


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
    def config(self) -> NotifierConfig:
        return super().config  # type: ignore

    def _get_component_type(self) -> type[Notifier]:  # type: ignore
        return Notifier

    def _get_component_context(self) -> NotifierContext:
        return NotifierContext(
            id=self._context.id,
            path=self._context.path,
            config=self._context.config,
            unit=self._context.unit,
        )

    async def notify(self) -> None:
        users = self._context.config.users
        database = self._context.database
        lookback = self.config.lookback
        cutoff = get_now() - lookback

        async with database.session() as session:
            alerts = [
                Alert.create_from(entity)
                for entity in await session.scalars(
                    select(AlertEntity).where(AlertEntity.timestamp > cutoff)
                )
            ]

        self.logger.info(
            f"{len(alerts)} alert(s) were emitted in the last {encode_td(lookback)}...",
        )

        if not users:
            self.logger.warning("No users exist to send notifications to.")
            return

        self.logger.info(f"Sending email notification to {len(users)} user(s).")
        await self.send(self._context.config.users, alerts)
        self.logger.info("Email notification sent successfully.")

    async def send(self, users: Sequence[UserConfig], alerts: list[Alert]) -> None:
        if not self._instance:
            raise ComponentNotLoadedException("Notifier is not loaded.")

        await self._instance.send(users, alerts)

    async def _tasklet_run(self) -> None:
        await super()._tasklet_run()

        if self.config.schedule:
            self.logger.info(f"Scheduling notifications as: {self.config.schedule}")
            self.scheduler.add_job(self.notify, self.config.schedule)
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
