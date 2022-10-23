from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from .component import Component, ComponentContext
from .config import ConnectionConfig
from .path import ConnectionPath, LocalConnectionPath
from .protocols import ReferencedConnectionHandle
from .reference import Reference


@dataclass(kw_only=True, frozen=True)
class ConnectionContext(ComponentContext):
    path: ConnectionPath


class Connection(Component[ConnectionContext], ABC):
    @property
    def config(self) -> ConnectionConfig | None:
        return super().config  # type: ignore

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, data: bytes) -> None:
        raise NotImplementedError()

    async def receive(self) -> bytes:
        raise NotImplementedError()


class ConnectionReference(Reference[ReferencedConnectionHandle]):
    @property
    def path(self) -> LocalConnectionPath:
        return LocalConnectionPath(self.name)
