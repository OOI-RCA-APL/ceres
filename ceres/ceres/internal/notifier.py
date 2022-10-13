from __future__ import annotations

from dataclasses import dataclass
from logging import Logger
from uuid import UUID

from ..alert import Alert
from ..config import UserConfig
from ..errors import ComponentError
from ..exceptions import ComponentNotLoadedException
from ..internal import logs
from ..notifier import Notifier, NotifierContext
from ..path import NotifierPath
from ..protocols import ReferencedNotifierHandle
from ..result import Ok, Result
from .component import ComponentHandleContext, load_component
from .tasks import Tasklet


class NotifierHandle(Tasklet, ReferencedNotifierHandle):
    def __init__(self, context: NotifierHandleContext) -> None:
        self._context = context
        self._instance: Notifier | None = None

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def path(self) -> NotifierPath:
        return self._context.path

    @property
    def instance(self) -> Notifier | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.path))

    async def load(self) -> Result[Notifier, ComponentError]:
        if not self._instance:
            match load_component(Notifier, self._context.component, self._context.parameters):
                case Ok(instance):
                    self._instance = instance
                    self._instance.setup(
                        NotifierContext(
                            id=self._context.id,
                            path=self._context.path,
                            unit=self._context.unit,
                            references=self._context.references,
                        )
                    )
                case fail:
                    return fail

        return Ok(self._instance)

    async def send(self, users: list[UserConfig], alerts: list[Alert]) -> None:
        if not self._instance:
            raise ComponentNotLoadedException("Notifier is not loaded.")

        await self._instance.send(users, alerts)

    async def _tasklet_run(self) -> None:
        pass

    async def _tasklet_stop(self) -> None:
        pass


@dataclass(kw_only=True, frozen=True)
class NotifierHandleContext(ComponentHandleContext):
    path: NotifierPath
