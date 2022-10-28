from __future__ import annotations

from dataclasses import field
from typing import Literal, overload

from pydantic.dataclasses import dataclass as validated_dataclass


@validated_dataclass(frozen=True)
class UnitPath:
    name: str
    kind: Literal["unit"] = field(default="unit", init=False)

    def __str__(self) -> str:
        return f"@{self.name}"

    @property
    def unit(self) -> str:
        return self.name


@validated_dataclass(frozen=True)
class ComponentPath:
    unit: str
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f"@{self.unit}.{self.name}"


PathKind = Literal["unit", "component"]
Path = UnitPath | ComponentPath


@validated_dataclass(frozen=True)
class LocalUnitPath:
    kind: Literal["unit"] = field(default="unit")

    def __str__(self) -> str:
        return "."


@validated_dataclass(frozen=True)
class LocalComponentPath:
    name: str
    kind: Literal["component"] = field(default="component")

    def __str__(self) -> str:
        return f".{self.name}"


LocalPath = LocalUnitPath | LocalComponentPath


@overload
def create_path(kind: Literal["unit"], unit: str) -> UnitPath:
    ...


@overload
def create_path(kind: Literal["component"], unit: str, name: str) -> ComponentPath:
    ...


def create_path(kind: PathKind, unit: str, name: str = "") -> Path:
    match kind:
        case "unit":
            return UnitPath(unit)
        case "component":
            return ComponentPath(unit, name)

    raise ValueError(kind)


@overload
def create_local_path(kind: Literal["unit"]) -> LocalUnitPath:
    ...


@overload
def create_local_path(kind: Literal["component"], name: str) -> LocalComponentPath:
    ...


def create_local_path(kind: PathKind, name: str = "") -> LocalPath:
    match kind:
        case "unit":
            return LocalUnitPath()
        case "connection":
            return LocalComponentPath(name)

    raise ValueError(kind)
