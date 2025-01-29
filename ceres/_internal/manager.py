from __future__ import annotations

from abc import ABC
from typing import Any, override

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres.database import Database
    from ceres.node import Node


class BaseManager[T](ABC):
    __slots__ = (
        "_source",
        "_cls",
    )

    def __init__(self, source: Database | Node, cls: type[T]) -> None:
        self._source = source
        self._cls = cls

    @property
    def _node(self) -> Node | None:
        if isinstance(self._source, Database):
            return None

        return self._source

    @property
    def _database(self) -> Database:
        if isinstance(self._source, Database):
            return self._source

        return self._source.database


class BaseBoundManager[T](BaseManager[T]):
    def __init__(self, source: Node, cls: type[T]) -> None:
        super().__init__(source, cls)

    @property
    @override
    def _node(self) -> Node:
        node = super()._node
        assert node is not None
        return node


AnyManager = BaseManager[Any]
