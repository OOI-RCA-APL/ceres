from __future__ import annotations

from abc import ABC
from typing import Any, Generic, TypeVar

from pydantic import BaseModel
from typing_extensions import override

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__):
    from ceres.database.database import Database
    from ceres.node import Node

_ModelT = TypeVar("_ModelT", bound=BaseModel)


class BaseManager(Generic[_ModelT], ABC):
    __slots__ = ("_source", "_cls")

    def __init__(self, source: Database | Node, cls: type[_ModelT]) -> None:
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


class BaseBoundManager(BaseManager[_ModelT], ABC):
    def __init__(self, source: Node, cls: type[_ModelT]) -> None:
        super().__init__(source, cls)

    @property
    @override
    def _node(self) -> Node:
        node = super()._node
        assert node is not None
        return node


AnyManager = BaseManager[Any]
