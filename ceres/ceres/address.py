from dataclasses import field
from typing import Literal, TypeAlias, overload

from .data import ValidatedDataclass


class UnitAddress(ValidatedDataclass, kw_only=False, frozen=True):
    name: str
    kind: Literal["unit"] = field(default="unit", init=False)

    def __str__(self) -> str:
        return f"@{self.name}"

    @property
    def unit(self) -> str:
        return self.name


class GlobalComponentAddress(ValidatedDataclass, kw_only=False, frozen=True):
    unit: str
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f"@{self.unit}.{self.name}"

    @property
    def component(self) -> str:
        return self.name


AddressKind: TypeAlias = Literal["unit", "component"]
Address: TypeAlias = UnitAddress | GlobalComponentAddress


class LocalUnitAddress(ValidatedDataclass, kw_only=False, frozen=True):
    kind: Literal["unit"] = field(default="unit")

    def __str__(self) -> str:
        return "."


class LocalComponentAddress(ValidatedDataclass, kw_only=False, frozen=True):
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f".{self.name}"


LocalAddress: TypeAlias = LocalUnitAddress | LocalComponentAddress


@overload
def caddr(unit_or_component: str, component: str, /) -> GlobalComponentAddress:
    ...


@overload
def caddr(unit_or_component: str, component: None = None, /) -> LocalComponentAddress:
    ...


def caddr(
    unit_or_component: str,
    component: str | None = None,
    /,
) -> GlobalComponentAddress | LocalComponentAddress:
    if component is None:
        return LocalComponentAddress(unit_or_component)

    return GlobalComponentAddress(unit_or_component, component)


ComponentAddress: TypeAlias = GlobalComponentAddress | LocalComponentAddress
