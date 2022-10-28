from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from .alert import Alert
from .events import Event
from .path import ComponentPath, LocalComponentPath

if TYPE_CHECKING:
    from .component import Component
    from .connection import Connection
    from .driver import Driver
    from .notifier import Notifier


@runtime_checkable
class ReferencedComponentHandle(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def path(self) -> ComponentPath:
        ...

    @property
    def instance(self) -> Component | None:
        ...


@runtime_checkable
class ReferencedConnectionHandle(ReferencedComponentHandle, Protocol):
    @property
    def instance(self) -> Connection | None:
        ...


@runtime_checkable
class ReferencedDriverHandle(ReferencedComponentHandle, Protocol):
    @property
    def instance(self) -> Driver | None:
        ...


@runtime_checkable
class ReferencedNotifierHandle(ReferencedComponentHandle, Protocol):
    @property
    def instance(self) -> Notifier | None:
        ...


@runtime_checkable
class GlobalUnitProtocol(Protocol):
    def get_component(self, path: LocalComponentPath) -> ReferencedComponentHandle | None:
        ...

    async def handle_event(self, event: Event) -> None:
        ...

    async def handle_alert(self, alert: Alert) -> None:
        ...
