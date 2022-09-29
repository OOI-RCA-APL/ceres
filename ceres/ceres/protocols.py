from __future__ import annotations

from typing import Protocol, runtime_checkable

from .events import Event
from .message import Message


@runtime_checkable
class BoundConnection(Protocol):
    async def send(self, data: bytes) -> Message:
        ...


@runtime_checkable
class GlobalUnitProtocol(Protocol):
    def get_connection(self, name: str) -> BoundConnection | None:
        ...

    async def broadcast(self, event: Event) -> None:
        ...
