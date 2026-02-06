from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.database import Database
    from ceres.node import Node


@runtime_checkable
class DatabaseSource(Protocol):
    __slots__ = ()

    @property
    def __database__(self) -> Database: ...

    def __get_filter_defaults__(self) -> dict[str, str]: ...


@runtime_checkable
class NodeSource(DatabaseSource, Protocol):
    __slots__ = ()

    @property
    def __node__(self) -> Node: ...


@runtime_checkable
class ComponentSource(NodeSource, Protocol):
    __slots__ = ()

    @property
    def __system__(self) -> ComponentSystem: ...

    @property
    def __component__(self) -> Component: ...
