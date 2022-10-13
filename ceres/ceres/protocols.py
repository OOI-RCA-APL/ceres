from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from .events import Event
from .message import Message
from .path import ConnectionPath, DriverPath, NotifierPath

if TYPE_CHECKING:
    from .connection import Connection
    from .driver import Driver
    from .notifier import Notifier


@runtime_checkable
class ReferencedConnectionHandle(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def path(self) -> ConnectionPath:
        ...

    @property
    def instance(self) -> Connection | None:
        ...

    async def send(self, data: bytes) -> Message:
        ...


@runtime_checkable
class ReferencedDriverHandle(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def path(self) -> DriverPath:
        ...

    @property
    def instance(self) -> Driver | None:
        ...


@runtime_checkable
class ReferencedNotifierHandle(Protocol):
    @property
    def id(self) -> UUID:
        ...

    @property
    def path(self) -> NotifierPath:
        ...

    @property
    def instance(self) -> Notifier | None:
        ...


@runtime_checkable
class GlobalUnitProtocol(Protocol):
    def get_connection(self, name: str) -> ReferencedConnectionHandle | None:
        ...

    def get_driver(self, name: str) -> ReferencedDriverHandle | None:
        ...

    def get_notifier(self, name: str) -> ReferencedNotifierHandle | None:
        ...

    async def broadcast(self, event: Event) -> None:
        ...
