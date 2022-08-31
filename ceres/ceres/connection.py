from __future__ import annotations

from abc import ABC
from uuid import UUID

from .component import Component, ComponentContext
from .path import ConnectionPath


class ConnectionContext(ComponentContext):
    id: UUID
    path: ConnectionPath


class Connection(Component[ConnectionContext], ABC):
    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, data: str) -> None:
        raise NotImplementedError()

    async def receive(self) -> str:
        raise NotImplementedError()
