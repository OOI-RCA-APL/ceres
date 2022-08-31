from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ComponentPathKind = Literal["connection"]
PathKind = Literal["unit", "connection"]


class BasePath(BaseModel):
    class Config:
        frozen = True

    kind: PathKind


class UnitPath(BasePath):
    kind: Literal["unit"] = "unit"
    unit: str

    @classmethod
    def create(cls, unit: str) -> UnitPath:
        return UnitPath(unit=unit)

    def __str__(self) -> str:
        return f"@{self.unit}"


class ConnectionPath(BasePath):
    kind: Literal["connection"] = "connection"
    unit: str
    connection: str

    @classmethod
    def create(cls, unit: str, connection: str) -> ConnectionPath:
        return ConnectionPath(unit=unit, connection=connection)

    def __str__(self) -> str:
        return f"@{self.unit}.connections.{self.connection}"


Path = UnitPath | ConnectionPath
ComponentPath = ConnectionPath
