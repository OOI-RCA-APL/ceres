from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Generic, Sequence, TypeVar, overload

from .path import LocalComponentPath

if TYPE_CHECKING:
    from .component import ComponentInterface

SelfT = TypeVar("SelfT", bound="ComponentReference")
ComponentT = TypeVar("ComponentT", bound="ComponentInterface")


class ComponentReference(Generic[ComponentT]):
    def __init__(self, cls: type[ComponentT], name: str) -> None:
        self.cls = cls
        self.name = name

    @property
    def path(self) -> LocalComponentPath:
        return LocalComponentPath(self.name)

    @overload
    def __get__(self: SelfT, component: None, owner: Any) -> SelfT:
        ...

    @overload
    def __get__(self: SelfT, component: ComponentT, owner: Any) -> ComponentT:
        ...

    def __get__(
        self: SelfT,
        component: ComponentT | None,
        owner: Any,
    ) -> SelfT | ComponentT:
        if component is None:
            return self

        if (name := component.context.references.get(self.name)) is None:
            raise ValueError(f"'{self.name}' is not defined in references of component {self.name}")

        raise ValueError(f"no component '{name}' in current unit")


@dataclass(kw_only=True, frozen=True)
class ReferenceBinding:
    cls: type[ComponentInterface]
    name: str

    @property
    def path(self) -> LocalComponentPath:
        return LocalComponentPath(self.name)


@cache
def get_reference_bindings(cls: type) -> Sequence[ReferenceBinding]:
    results: list[ReferenceBinding] = []

    for _, member in inspect.getmembers(cls):
        if isinstance(member, ComponentReference):
            results.append(
                ReferenceBinding(
                    cls=member.cls,
                    name=member.name,
                )
            )

    return tuple(results)
