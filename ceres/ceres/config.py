from __future__ import annotations

import itertools
from abc import ABC
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, validator

_NAME_REGEX = r"[a-zA-Z\-\_][a-zA-Z0-9\-\_]*"


class ComponentReferencesConfig(BaseModel):
    connections: dict[str, str] = {}
    drivers: dict[str, str] = {}


class ComponentConfig(BaseModel, ABC):
    class Config:
        arbitrary_types_allowed = True

    name: str = Field(regex=_NAME_REGEX)
    component: str | object
    parameters: dict[str, Any] = {}
    references: ComponentReferencesConfig = ComponentReferencesConfig()


class ReconnectConfig(BaseModel):
    interval: float = 1
    backoff: float | None = None
    max_interval: float | None = 60 * 5


class ConnectionConfig(ComponentConfig):
    reconnect: ReconnectConfig = ReconnectConfig()


class DriverConfig(ComponentConfig):
    pass


class ServerConfig(BaseModel):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"


class DatabaseRetryConfig(BaseModel):
    attempts: int | None = Field(default=None, gt=0)
    timeout: float = Field(gt=0)


class BaseDatabaseConfig(BaseModel):
    kind: DatabaseKind
    engine: dict[str, Any] | None = None
    retry: DatabaseRetryConfig = DatabaseRetryConfig(timeout=30)


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path


DatabaseConfig = SQLiteDatabaseConfig


class UnitConfig(BaseModel):
    name: str = Field(regex=_NAME_REGEX)
    connections: list[ConnectionConfig] = []
    drivers: list[DriverConfig] = []

    @validator("connections")
    def _check_connections(cls, connections: list[ConnectionConfig]) -> list[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections

    @validator("drivers")
    def _check_drivers(cls, connections: list[DriverConfig]) -> list[DriverConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate driver name '{name}'")

        return connections


class Config(BaseModel):
    server: ServerConfig
    database: DatabaseConfig
    units: list[UnitConfig] = []

    __path__: str | None = PrivateAttr(default=None)

    @property
    def path(self) -> str | None:
        return self.__path__

    @validator("units")
    def _check_units(cls, units: list[UnitConfig]) -> list[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units
