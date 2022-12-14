from dataclasses import field
from typing import Literal, overload

from .data import ValidatedDataclass


class UnitAddress(ValidatedDataclass, kw_only=False, frozen=True):
    name: str
    kind: Literal["unit"] = field(default="unit", init=False)

    def __str__(self) -> str:
        return f"@{self.name}"

    @property
    def unit(self) -> str:
        return self.name


class ComponentAddress(ValidatedDataclass, kw_only=False, frozen=True):
    unit: str
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f"@{self.unit}.{self.name}"

    @property
    def component(self) -> str:
        return self.name


AddressKind = Literal["unit", "component"]
Address = UnitAddress | ComponentAddress


class LocalUnitAddress(ValidatedDataclass, kw_only=False, frozen=True):
    kind: Literal["unit"] = field(default="unit")

    def __str__(self) -> str:
        return "."


class LocalComponentAddress(ValidatedDataclass, kw_only=False, frozen=True):
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f".{self.name}"


LocalAddress = LocalUnitAddress | LocalComponentAddress


@overload
def create_address(kind: Literal["unit"], unit: str) -> UnitAddress:
    ...


@overload
def create_address(kind: Literal["component"], unit: str, name: str) -> ComponentAddress:
    ...


def create_address(kind: AddressKind, unit: str, name: str = "") -> Address:
    match kind:
        case "unit":
            return UnitAddress(unit)
        case "component":
            return ComponentAddress(unit, name)

    raise ValueError(kind)


@overload
def create_local_address(kind: Literal["unit"]) -> LocalUnitAddress:
    ...


@overload
def create_local_address(kind: Literal["component"], name: str) -> LocalComponentAddress:
    ...


def create_local_address(kind: AddressKind, name: str = "") -> LocalAddress:
    match kind:
        case "unit":
            return LocalUnitAddress()
        case "component":
            return LocalComponentAddress(name)

    raise ValueError(kind)
