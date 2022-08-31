from __future__ import annotations

import itertools
from abc import ABC
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, validator


class ComponentConfig(BaseModel, ABC):
    class Config:
        allow_arbitrary_types = True

    name: str
    component: str | object
    parameters: dict[str, Any] = {}


class ReconnectConfig(BaseModel):
    interval: float = 1
    backoff: float | None = None
    max_interval: float | None = 60 * 5


class ConnectionConfig(ComponentConfig):
    reconnect: ReconnectConfig = ReconnectConfig()


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
    name: str
    connections: list[ConnectionConfig] = []

    @validator("connections")
    def _check_connections(cls, connections: list[ConnectionConfig]) -> list[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

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
