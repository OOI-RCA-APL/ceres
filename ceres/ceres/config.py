from __future__ import annotations

import itertools
import re
from abc import ABC
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseConfig,
    BaseModel,
    ConstrainedStr,
    Field,
    PrivateAttr,
    root_validator,
    validator,
)

from .internal.utilities import decode_timedelta, encode_timedelta


class NameStr(ConstrainedStr):
    regex = re.compile(r"[a-zA-Z\-\_][a-zA-Z0-9\-\_]*")


class EmailStr(ConstrainedStr):
    regex = re.compile(r".+@.+")


class ComponentReferencesConfig(BaseModel):
    connections: dict[str, str] = {}
    drivers: dict[str, str] = {}
    notifiers: dict[str, str] = {}


class ComponentConfig(BaseModel, ABC):
    class Config:
        arbitrary_types_allowed = True

    name: NameStr
    component: str | object
    parameters: dict[str, Any] = {}
    references: ComponentReferencesConfig = ComponentReferencesConfig()


class ReconnectConfig(BaseModel):
    interval: timedelta = timedelta(seconds=1)
    backoff: float | None = 2
    max_interval: timedelta | None = timedelta(seconds=60)

    @validator("interval", "max_interval", pre=True)
    def _check_timedeltas(value: Any) -> timedelta:
        return decode_timedelta(value)


class ConnectionConfig(ComponentConfig):
    reconnect: ReconnectConfig = ReconnectConfig()


class DriverConfig(ComponentConfig):
    pass


class NotifierConfig(ComponentConfig):
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
    name: NameStr
    connections: list[ConnectionConfig] = []
    drivers: list[DriverConfig] = []
    notifiers: list[NotifierConfig] = []

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

    @root_validator
    def _check_references(cls, fields: dict[str, Any]) -> dict[str, Any]:
        name: str = fields["name"]
        connections: dict[str, ConnectionConfig] = {
            current.name: current for current in fields.get("connections", [])
        }
        drivers: dict[str, DriverConfig] = {
            current.name: current for current in fields.get("drivers", [])
        }
        components: list[ComponentConfig] = [*connections.values(), *drivers.values()]

        for component in components:
            for name in component.references.connections.values():
                if name not in connections:
                    raise ValueError(
                        f"invalid reference, connection '{name}' does not exist in unit '{name}'"
                    )

            for name in component.references.drivers.values():
                if name not in connections:
                    raise ValueError(
                        f"invalid reference, driver '{name}' does not exist in unit '{name}'"
                    )

        return fields


class UserConfig(BaseModel):
    username: NameStr
    email: EmailStr
    meta: dict[str, Any] = {}


class Config(BaseModel):
    class Config(BaseConfig):
        json_encoders = {
            timedelta: encode_timedelta,
        }

    server: ServerConfig
    database: DatabaseConfig
    users: list[UserConfig] = []
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
