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
class ConnectionPath:
    unit: str
    name: str
    kind: Literal["connection"] = field(default="connection")

    def __str__(self) -> str:
        return f"@{self.unit}.connections.{self.name}"


@validated_dataclass(frozen=True)
class DriverPath:
    unit: str
    name: str
    kind: Literal["driver"] = field(default="driver")

    def __str__(self) -> str:
        return f"@{self.unit}.drivers.{self.name}"


@validated_dataclass(frozen=True)
class NotifierPath:
    unit: str
    name: str
    kind: Literal["notifier"] = field(default="notifier")

    def __str__(self) -> str:
        return f"@{self.unit}.notifiers.{self.name}"


ComponentPathKind = Literal["connection", "driver", "notifier"]
ComponentPath = ConnectionPath | DriverPath | NotifierPath

PathKind = Literal["unit"] | ComponentPathKind  # type: ignore
Path = UnitPath | ComponentPath


@validated_dataclass(frozen=True)
class LocalUnitPath:
    kind: Literal["unit"] = field(default="unit")

    def __str__(self) -> str:
        return "."


@validated_dataclass(frozen=True)
class LocalConnectionPath:
    name: str
    kind: Literal["connection"] = field(default="connection")

    def __str__(self) -> str:
        return f".connections.{self.name}"


@validated_dataclass(frozen=True)
class LocalDriverPath:
    name: str
    kind: Literal["driver"] = field(default="driver")

    def __str__(self) -> str:
        return f".drivers.{self.name}"


@validated_dataclass(frozen=True)
class LocalNotifierPath:
    name: str
    kind: Literal["notifier"] = field(default="notifier")

    def __str__(self) -> str:
        return f".notifiers.{self.name}"


LocalComponentPath = LocalConnectionPath | LocalDriverPath | LocalNotifierPath
LocalPath = LocalUnitPath | LocalComponentPath


@overload
def create_path(kind: Literal["unit"], unit: str) -> UnitPath:
    ...


@overload
def create_path(kind: Literal["connection"], unit: str, name: str) -> ConnectionPath:
    ...


@overload
def create_path(kind: Literal["driver"], unit: str, name: str) -> DriverPath:
    ...


@overload
def create_path(kind: Literal["notifier"], unit: str, name: str) -> NotifierPath:
    ...


def create_path(kind: PathKind, unit: str, name: str = "") -> Path:
    match kind:
        case "unit":
            return UnitPath(unit)
        case "connection":
            return ConnectionPath(unit, name)
        case "driver":
            return DriverPath(unit, name)
        case "notifier":
            return NotifierPath(unit, name)

    raise ValueError(kind)


@overload
def create_local_path(kind: Literal["unit"]) -> LocalUnitPath:
    ...


@overload
def create_local_path(kind: Literal["connection"], name: str) -> LocalConnectionPath:
    ...


@overload
def create_local_path(kind: Literal["driver"], name: str) -> LocalDriverPath:
    ...


@overload
def create_local_path(kind: Literal["notifier"], name: str) -> LocalNotifierPath:
    ...


def create_local_path(kind: PathKind, name: str = "") -> LocalPath:
    match kind:
        case "unit":
            return LocalUnitPath()
        case "connection":
            return LocalConnectionPath(name)
        case "driver":
            return LocalDriverPath(name)
        case "notifier":
            return LocalNotifierPath(name)

    raise ValueError(kind)
