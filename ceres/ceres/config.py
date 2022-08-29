from __future__ import annotations

import itertools
import os
from abc import ABC
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import PrivateAttr, ValidationError, validator
from yaml import YAMLError

from .data import DataObject
from .exceptions import ConfigException
from .internal import format_validation_error


class ComponentConfig(DataObject, ABC):
    class Config:
        allow_arbitrary_types = True

    name: str
    component: str | object
    parameters: dict[str, Any] = {}


class ReconnectConfig(DataObject):
    interval: float = 1
    backoff: float | None = None
    max_interval: float | None = 60 * 5


class ConnectionConfig(ComponentConfig):
    reconnect: ReconnectConfig = ReconnectConfig()


class ServerConfig(DataObject):
    port: int
    enable: bool = True


DatabaseType = Literal["sqlite"]


class BaseDatabaseConfig(DataObject):
    type: DatabaseType
    engine: dict[str, Any] | None = None


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    type: Literal["sqlite"] = "sqlite"
    path: Path


DatabaseConfig = SQLiteDatabaseConfig


class UnitConfig(DataObject):
    name: str
    connections: list[ConnectionConfig] = []

    @validator("connections")
    def _check_connections(cls, connections: list[ConnectionConfig]) -> list[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections


class EngineConfig(DataObject):
    server: ServerConfig
    database: DatabaseConfig
    units: list[UnitConfig] = []

    __path__: str = PrivateAttr(default="")

    @property
    def path(self) -> str:
        return self.__path__

    @validator("units")
    def _check_units(cls, units: list[UnitConfig]) -> list[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units

    @classmethod
    def load(cls, path: str) -> EngineConfig:
        try:
            path = os.path.realpath(path)
        except Exception:
            raise ConfigException(f"Configuration file path '{path}' could not be resolved.")

        try:
            with open(path, "r") as stream:
                data = yaml.safe_load(stream)
        except OSError:
            raise ConfigException(
                f"Configuration file at '{path}' does not exist or is not readable."
            )
        except YAMLError:
            raise ConfigException(f"Configuration file at '{path}' is not valid YAML or JSON.")

        try:
            config = EngineConfig.parse_obj(data)
        except ValidationError as error:
            raise ConfigException(
                f"Configuration file at '{path}' is invalid:\n{format_validation_error(error)}"
            )

        config.__path__ = path
        return config
