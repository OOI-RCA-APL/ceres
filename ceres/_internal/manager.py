from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, override

from ceres._internal.protocols import ComponentSource, DatabaseSource, NodeSource

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.database import Database
    from ceres.node import Node


class BaseDatabaseManager(ABC, DatabaseSource):
    __slots__ = ("__source__",)

    def __init__(self, source: DatabaseSource, /) -> None:
        self.__source__ = source

    @property
    @override
    def __database__(self) -> Database:
        return self.__source__.__database__

    @override
    def __get_filter_defaults__(self) -> dict[str, Any]:
        return self.__source__.__get_filter_defaults__()


class BaseNodeManager(BaseDatabaseManager, NodeSource):
    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __node__(self) -> Node:
        return self.__source__.__node__


class BaseComponentManager(BaseNodeManager, ComponentSource):
    def __init__(self, source: ComponentSource, /) -> None:
        super().__init__(source)
        self.__source__ = source

    @property
    @override
    def __component__(self) -> Component:
        return self.__source__.__component__

    @property
    @override
    def __system__(self) -> ComponentSystem:
        return self.__source__.__system__
