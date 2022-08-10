import os
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional, Union

import yaml
from pydantic import BaseModel, PrivateAttr, ValidationError, validator
from pydantic.error_wrappers import display_errors
from yaml import YAMLError

from .exceptions import ConfigException

if TYPE_CHECKING:
    from .connection import Connection


class ObjectDefinition(BaseModel, ABC):
    module: Optional[str] = None
    instance: Optional[Any] = None

    class Config:
        allow_arbitrary_types = True

    @validator("module")
    def _validate_module(cls, module: Optional[str], values: Dict[str, Any]) -> Optional[str]:
        if module is None and values.get("instance") is None:
            raise ValueError("module must be provided")

        return module


class ReconnectConfig(BaseModel):
    interval: float = 1
    backoff: Optional[float] = None
    max_interval: Optional[float] = 60 * 5


class ConnectionDefinition(ObjectDefinition):
    instance: Optional["Connection"] = None
    reconnect: ReconnectConfig = ReconnectConfig()


class ServerConfig(BaseModel):
    port: int
    enable: bool = True


class SQLiteDatabaseConfig(BaseModel):
    type: Literal["sqlite"]
    path: str = ":memory:"
    echo: bool = False


class PostgresDatabaseConfig(BaseModel):
    type: Literal["postgres"]
    host: str = "0.0.0.0"
    port: int = 5432
    name: str = "epems"
    user: str = "epems"
    password: str
    echo: bool = False


DatabaseConfig = Union[SQLiteDatabaseConfig, PostgresDatabaseConfig]


class UnitConfig(BaseModel):
    connections: Dict[str, ConnectionDefinition] = {}


class Config(BaseModel):
    database: DatabaseConfig = SQLiteDatabaseConfig(type="sqlite")
    server: Optional[ServerConfig] = None
    units: Dict[str, UnitConfig] = {}

    __path__: str = PrivateAttr(default="")

    @property
    def path(self) -> str:
        return self.__path__

    @classmethod
    def load(cls, path: str) -> "Config":
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
            config = Config.parse_obj(data)
        except ValidationError as error:
            raise ConfigException(
                f"Configuration file at '{path}' is invalid:\n{display_errors(error.errors())}"
            )

        config.__path__ = path
        return config
