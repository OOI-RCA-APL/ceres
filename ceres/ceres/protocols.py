from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

from .events import Event
from .message import Message
from .path import ConnectionPath, DriverPath

if TYPE_CHECKING:
    from .connection import Connection
    from .driver import Driver


@runtime_checkable
class ReferencedConnectionHandleProtocol(Protocol):
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
class ReferencedDriverHandleProtocol(Protocol):
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
class GlobalUnitProtocol(Protocol):
    def get_connection(self, name: str) -> ReferencedConnectionHandleProtocol | None:
        ...

    def get_driver(self, name: str) -> ReferencedDriverHandleProtocol | None:
        ...

    async def broadcast(self, event: Event) -> None:
        ...
