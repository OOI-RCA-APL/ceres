from __future__ import annotations

import inspect
from abc import abstractmethod, abstractproperty
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Generic, Sequence, TypeVar, overload

from .path import LocalComponentPath

if TYPE_CHECKING:
    from .component import Component, ContextT


SelfT = TypeVar("SelfT", bound="Reference[Any]")
TargetT = TypeVar("TargetT")


class Reference(Generic[TargetT]):
    def __init__(self, name: str) -> None:
        self.name = name

    @abstractproperty
    def path(self) -> LocalComponentPath:
        raise NotImplementedError()

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
        raise NotImplementedError()


@dataclass(kw_only=True, frozen=True)
class ReferenceBinding:
    path: LocalComponentPath


@cache
def get_reference_bindings(cls: type) -> Sequence[ReferenceBinding]:
    results: list[ReferenceBinding] = []

    for _, member in inspect.getmembers(cls):
        if isinstance(member, Reference):
            results.append(ReferenceBinding(path=member.path))

    return tuple(results)
