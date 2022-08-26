import itertools
import os
from abc import ABC
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import PrivateAttr, ValidationError, validator
from pydantic.error_wrappers import display_errors
from yaml import YAMLError

from .data import DataObject
from .exceptions import ConfigException


class ComponentConfig(DataObject, ABC):
    class Config:
        allow_arbitrary_types = True

    name: str
    component: Union[str, object]


class ReconnectConfig(DataObject):
    interval: float = 1
    backoff: Optional[float] = None
    max_interval: Optional[float] = 60 * 5


class ConnectionConfig(ComponentConfig):
    reconnect: ReconnectConfig = ReconnectConfig()


class ServerConfig(DataObject):
    port: int
    enable: bool = True


DatabaseType = Literal["sqlite"]


class BaseDatabaseConfig(DataObject):
    type: DatabaseType
    engine: Optional[Dict[str, Any]] = None


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    type: Literal["sqlite"] = "sqlite"
    path: Path


DatabaseConfig = SQLiteDatabaseConfig


class UnitConfig(DataObject):
    name: str
    connections: List[ConnectionConfig] = []

    @validator("connections")
    def _check_connections(cls, connections: List[ConnectionConfig]) -> List[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections


class EngineConfig(DataObject):
    server: ServerConfig
    database: DatabaseConfig
    units: List[UnitConfig] = []

    __path__: str = PrivateAttr(default="")

    @property
    def path(self) -> str:
        return self.__path__

    @validator("units")
    def _check_units(cls, units: List[UnitConfig]) -> List[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units

    @classmethod
    def load(cls, path: str) -> "EngineConfig":
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
                f"Configuration file at '{path}' is invalid:\n{display_errors(error.errors())}"
            )

        config.__path__ = path
        return config
