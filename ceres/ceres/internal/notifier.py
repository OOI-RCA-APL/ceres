from __future__ import annotations

from dataclasses import dataclass

from ..alert import Alert
from ..config import UserConfig
from ..exceptions import ComponentNotLoadedException
from ..notifier import Notifier, NotifierContext
from ..path import NotifierPath
from ..protocols import ReferencedNotifierHandle
from .component import ComponentHandle, ComponentHandleContext
from .tasks import Tasklet


@dataclass(kw_only=True, frozen=True)
class NotifierHandleContext(ComponentHandleContext):
    path: NotifierPath


class NotifierHandle(
    ComponentHandle[
        NotifierHandleContext,
        Notifier,
        NotifierContext,
    ],
    Tasklet,
    ReferencedNotifierHandle,
):
    @property
    def path(self) -> NotifierPath:
        return self._context.path

    def _get_component_type(self) -> type[Notifier]:  # type: ignore
        return Notifier

    def _get_component_context(self) -> NotifierContext:
        return NotifierContext(
            id=self._context.id,
            path=self._context.path,
            unit=self._context.unit,
            references=self._context.references,
        )

    async def send(self, users: list[UserConfig], alerts: list[Alert]) -> None:
        if not self._instance:
            raise ComponentNotLoadedException("Notifier is not loaded.")

        await self._instance.send(users, alerts)

    async def _tasklet_run(self) -> None:
        pass

    async def _tasklet_stop(self) -> None:
        pass
