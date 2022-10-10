from __future__ import annotations

from typing import Literal

from pydantic.dataclasses import dataclass


@dataclass(kw_only=True, frozen=True)
class UnitPath:
    kind: Literal["unit"] = "unit"
    name: str

    @classmethod
    def create(cls, name: str) -> UnitPath:
        return cls(name=name)

    def __str__(self) -> str:
        return f"@{self.name}"

    @property
    def unit(self) -> str:
        return self.name


@dataclass(kw_only=True, frozen=True)
class ConnectionPath:
    kind: Literal["connection"] = "connection"
    unit: str
    name: str

    @classmethod
    def create(cls, unit: str, name: str) -> ConnectionPath:
        return cls(unit=unit, name=name)

    def __str__(self) -> str:
        return f"@{self.unit}.connections.{self.name}"


@dataclass(kw_only=True, frozen=True)
class DriverPath:
    kind: Literal["driver"] = "driver"
    unit: str
    name: str

    @classmethod
    def create(cls, unit: str, name: str) -> DriverPath:
        return cls(unit=unit, name=name)

    def __str__(self) -> str:
        return f"@{self.unit}.drivers.{self.name}"


Path = UnitPath | ConnectionPath | DriverPath
ComponentPath = ConnectionPath | DriverPath


@dataclass(kw_only=True, frozen=True)
class LocalConnectionPath:
    kind: Literal["connection"] = "connection"
    name: str

    @classmethod
    def create(cls, name: str) -> LocalConnectionPath:
        return cls(name=name)

    def __str__(self) -> str:
        return f".connections.{self.name}"


@dataclass(kw_only=True, frozen=True)
class LocalDriverPath:
    kind: Literal["driver"] = "driver"
    name: str

    @classmethod
    def create(cls, name: str) -> LocalDriverPath:
        return cls(name=name)

    def __str__(self) -> str:
        return f".drivers.{self.name}"


LocalComponentPath = LocalConnectionPath | LocalDriverPath

ComponentPathKind = Literal["connection", "driver"]


def create_component_path(kind: ComponentPathKind, unit: str, name: str) -> ComponentPath:
    match kind:
        case "connection":
            return ConnectionPath.create(unit, name)
        case "driver":
            return DriverPath.create(unit, name)

    raise ValueError(kind)
