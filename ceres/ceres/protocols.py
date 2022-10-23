from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, overload, runtime_checkable
from uuid import UUID

from .alert import Alert
from .events import Event
from .message import Message
from .path import (
    ComponentPath,
    ConnectionPath,
    DriverPath,
    LocalConnectionPath,
    LocalDriverPath,
    LocalNotifierPath,
    NotifierPath,
)

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
    def path(self) -> ConnectionPath:
        ...

    @property
    def instance(self) -> Connection | None:
        ...

    async def send(self, data: bytes) -> Message:
        ...


@runtime_checkable
class ReferencedDriverHandle(ReferencedComponentHandle, Protocol):
    @property
    def path(self) -> DriverPath:
        ...

    @property
    def instance(self) -> Driver | None:
        ...


@runtime_checkable
class ReferencedNotifierHandle(ReferencedComponentHandle, Protocol):
    @property
    def path(self) -> NotifierPath:
        ...

    @property
    def instance(self) -> Notifier | None:
        ...


@runtime_checkable
class GlobalUnitProtocol(Protocol):
    @overload
    def get_component(self, path: LocalConnectionPath) -> ReferencedConnectionHandle | None:
        ...

    @overload
    def get_component(self, path: LocalDriverPath) -> ReferencedDriverHandle | None:
        ...

    @overload
    def get_component(self, path: LocalNotifierPath) -> ReferencedNotifierHandle | None:
        ...

    async def broadcast(self, event: Event) -> None:
        ...

    async def alert(self, alert: Alert) -> None:
        ...
