from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any

from .component import Component, ComponentContext, ContextT
from .path import ConnectionPath, LocalConnectionPath
from .protocols import ReferencedConnectionHandleProtocol
from .reference import Reference, SelfT


@dataclass(kw_only=True, frozen=True)
class ConnectionContext(ComponentContext):
    path: ConnectionPath


class Connection(Component[ConnectionContext], ABC):
    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        pass

    async def send(self, data: bytes) -> None:
        raise NotImplementedError()

    async def receive(self) -> bytes:
        raise NotImplementedError()


class ConnectionReference(Reference[ReferencedConnectionHandleProtocol]):
    @property
    def path(self) -> LocalConnectionPath:
        return LocalConnectionPath.create(self.name)

    def __get__(  # type: ignore
        self: SelfT,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> SelfT | ReferencedConnectionHandleProtocol:
        if component is None:
            return self

        if not (real_name := component.context.references.connections.get(self.name)):
            raise ValueError(f"connection '{self.name}' is not defined in connection references")

        if connection := component.context.unit.get_connection(real_name):
            return connection

        raise ValueError(f"no connection '{real_name}' in current unit")
