from __future__ import annotations

from typing import Protocol, runtime_checkable

from .message import Message


@runtime_checkable
class BoundConnection(Protocol):
    async def send(self, data: str) -> Message:
        ...


@runtime_checkable
class GlobalUnitProtocol(Protocol):
    def get_connection(self, name: str) -> BoundConnection | None:
        ...
