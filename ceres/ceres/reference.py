from __future__ import annotations

from abc import abstractmethod
from typing import Any, Generic, TypeVar, overload

from .component import Component, ContextT
from .path import LocalConnectionPath

SelfT = TypeVar("SelfT", bound="Reference[Any]")
TargetT = TypeVar("TargetT")


class Reference(Generic[TargetT]):
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def path(self) -> LocalConnectionPath:
        return LocalConnectionPath.create(self.name)

    @overload
    def __get__(self: SelfT, component: None, owner: Any) -> SelfT:
        ...

    @overload
    def __get__(self: SelfT, component: Component[ContextT], owner: Any) -> TargetT:
        ...

    @abstractmethod
    def __get__(
        self: SelfT,
        component: Component[ContextT] | None,
        owner: Any,
    ) -> SelfT | TargetT:
        ...
