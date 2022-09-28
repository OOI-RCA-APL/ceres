from __future__ import annotations

from abc import ABC
from typing import Literal

from pydantic import BaseModel


class BasePath(BaseModel, ABC):
    class Config:
        frozen = True


class UnitPath(BasePath):
    kind: Literal["unit"] = "unit"
    unit: str

    @classmethod
    def create(cls, unit: str) -> UnitPath:
        return UnitPath(unit=unit)

    def __str__(self) -> str:
        return f"@{self.unit}"

    @property
    def name(self) -> str:
        return self.unit


class ConnectionPath(BasePath):
    kind: Literal["connection"] = "connection"
    unit: str
    connection: str

    @classmethod
    def create(cls, unit: str, connection: str) -> ConnectionPath:
        return ConnectionPath(unit=unit, connection=connection)

    def __str__(self) -> str:
        return f"@{self.unit}.connections.{self.connection}"

    @property
    def name(self) -> str:
        return self.connection


class DriverPath(BasePath):
    kind: Literal["driver"] = "driver"
    unit: str
    driver: str

    @classmethod
    def create(cls, unit: str, driver: str) -> DriverPath:
        return DriverPath(unit=unit, driver=driver)

    def __str__(self) -> str:
        return f"@{self.unit}.drivers.{self.driver}"

    @property
    def name(self) -> str:
        return self.driver


Path = UnitPath | ConnectionPath | DriverPath
ComponentPath = ConnectionPath | DriverPath


class LocalConnectionPath(BasePath):
    kind: Literal["connection"] = "connection"
    connection: str

    @classmethod
    def create(cls, connection: str) -> LocalConnectionPath:
        return LocalConnectionPath(connection=connection)

    def __str__(self) -> str:
        return f".connections.{self.connection}"

    @property
    def name(self) -> str:
        return self.connection


class LocalDriverPath(BasePath):
    kind: Literal["driver"] = "driver"
    driver: str

    @classmethod
    def create(cls, driver: str) -> LocalDriverPath:
        return LocalDriverPath(driver=driver)

    def __str__(self) -> str:
        return f".drivers.{self.driver}"

    @property
    def name(self) -> str:
        return self.driver


LocalComponentPath = LocalConnectionPath | LocalDriverPath
