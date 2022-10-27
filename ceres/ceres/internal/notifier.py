from __future__ import annotations

from dataclasses import dataclass

from ..notifier import Notifier, NotifierContext
from ..path import NotifierPath
from ..protocols import ReferencedNotifierHandle
from .component import ComponentHandle, ComponentHandleContext


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
    @classmethod
    def _get_component_type(cls) -> type[Notifier]:
        return Notifier

    @property
    def path(self) -> NotifierPath:
        return self._context.path
