from __future__ import annotations

from abc import ABC
from typing import Any, overload
from uuid import UUID

from .component import Component, ComponentContext, ContextT
from .path import ConnectionPath, LocalConnectionPath
from .protocols import BoundConnection


class ConnectionContext(ComponentContext):
    id: UUID
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


class UseConnection:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def path(self) -> LocalConnectionPath:
        return LocalConnectionPath.create(self.name)

    @overload
    def __get__(self, component: None, owner: Any) -> UseConnection:
        ...

    @overload
    def __get__(self, component: Component[ContextT], owner: Any) -> BoundConnection:
        ...

    def __get__(
        self,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> UseConnection | BoundConnection:
        if component is None:
            return self

        if connection := component.context.unit.get_connection(self.name):
            return connection

        raise ValueError(f"no connection in unit named '{self.name}'")
