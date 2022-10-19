from __future__ import annotations

import inspect
from abc import abstractproperty
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Generic, Sequence, TypeVar, cast, overload

from .path import LocalComponentPath

if TYPE_CHECKING:
    from .component import Component, ComponentContext

SelfT = TypeVar("SelfT", bound="Reference")
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
    def __get__(self: SelfT, component: Component[ComponentContext], owner: Any) -> TargetT:
        ...

    def __get__(
        self: SelfT,
        component: Component[ComponentContext] | None,
        owner: Any,
    ) -> SelfT | TargetT:
        if component is None:
            return self

        if (path := component.context.references.remap(self.path)) is None:
            raise ValueError(
                f"{self.path.kind} '{self.name}' is not defined in {self.path.kind} references"
            )

        if target := component.context.unit.get_component(path):
            return cast(TargetT, target)

        raise ValueError(f"no {path.kind} '{path.name}' in current unit")


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
