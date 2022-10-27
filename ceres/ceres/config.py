from __future__ import annotations

import itertools
import sys
import warnings
from dataclasses import field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, overload

from pydantic import ConfigDict, Field, SecretStr, root_validator, validator
from pydantic.dataclasses import dataclass

from .internal.utilities import (
    EmailStr,
    NameStr,
    frozendict,
    frozenlist,
    hydrate,
    validate_positive_timedelta,
)
from .path import (
    ComponentPath,
    ConnectionPath,
    DriverPath,
    LocalComponentPath,
    LocalConnectionPath,
    LocalDriverPath,
    LocalNotifierPath,
    NotifierPath,
    UnitPath,
    create_local_path,
)


@dataclass(kw_only=True, frozen=True)
class BaseConfigObject:
    pass


@dataclass(kw_only=True, frozen=True)
class ComponentReferencesConfig(BaseConfigObject):
    connections: frozendict[str, str] = field(default_factory=frozendict)
    drivers: frozendict[str, str] = field(default_factory=frozendict)
    notifiers: frozendict[str, str] = field(default_factory=frozendict)

    def has(self, path: LocalComponentPath) -> bool:
        return self.remap(path) is not None

    def remap(self, path: LocalComponentPath) -> LocalComponentPath | None:
        match path:
            case LocalConnectionPath():
                name = self.connections.get(path.name)
            case LocalDriverPath():
                name = self.drivers.get(path.name)
            case LocalNotifierPath():
                name = self.notifiers.get(path.name)

        if name is None:
            return None

        return create_local_path(path.kind, name)


@dataclass(kw_only=True, frozen=True)
class ComponentConfig(BaseConfigObject):
    kind: Literal["connection", "driver", "notifier"]
    name: NameStr
    component: str | object
    parameters: frozendict[str, Any] = field(default_factory=frozendict)
    references: ComponentReferencesConfig = field(default_factory=ComponentReferencesConfig)


@dataclass(kw_only=True, frozen=True)
class ConnectionConfig(ComponentConfig):
    kind: Literal["connection"] = "connection"


@dataclass(kw_only=True, frozen=True)
class DriverConfig(ComponentConfig):
    kind: Literal["driver"] = "driver"


@dataclass(kw_only=True, frozen=True)
class NotifierConfig(ComponentConfig):
    kind: Literal["notifier"] = "notifier"


@dataclass(kw_only=True, frozen=True)
class ServerConfig(BaseConfigObject):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


@dataclass(kw_only=True, frozen=True)
class DatabaseRetryConfig(BaseConfigObject):
    timeout: timedelta = timedelta(seconds=15)
    interval: timedelta = timedelta(seconds=3)

    @validator("timeout", "interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@dataclass(kw_only=True, frozen=True)
class BaseDatabaseConfig(BaseConfigObject):
    kind: DatabaseKind
    engine: frozendict[str, Any] | None = None
    retry: DatabaseRetryConfig = field(default_factory=DatabaseRetryConfig)


@dataclass(kw_only=True, frozen=True)
class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path


@dataclass(kw_only=True, frozen=True)
class PostgresDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.POSTGRES] = DatabaseKind.POSTGRES
    host: str
    port: int
    database: str
    user: str
    password: SecretStr


DatabaseConfig = SQLiteDatabaseConfig | PostgresDatabaseConfig


@dataclass(kw_only=True, frozen=True)
class UnitConfig(BaseConfigObject):
    name: NameStr
    connections: frozenlist[ConnectionConfig] = field(default_factory=frozenlist)
    drivers: frozenlist[DriverConfig] = field(default_factory=frozenlist)
    notifiers: frozenlist[NotifierConfig] = field(default_factory=frozenlist)

    @validator("connections")
    def _validate_connections(
        cls,
        connections: Sequence[ConnectionConfig],
    ) -> Sequence[ConnectionConfig]:
        for name, group in itertools.groupby(connections, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate connection name '{name}'")

        return connections

    @validator("drivers")
    def _validate_drivers(
        cls,
        drivers: Sequence[DriverConfig],
    ) -> Sequence[DriverConfig]:
        for name, group in itertools.groupby(drivers, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate driver name '{name}'")

        return drivers

    @validator("notifiers")
    def _validate_notifiers(
        cls,
        notifiers: Sequence[NotifierConfig],
    ) -> Sequence[NotifierConfig]:
        for name, group in itertools.groupby(notifiers, lambda connection: connection.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate notifier name '{name}'")

        return notifiers

    @root_validator
    def _validate_references(cls, fields: Mapping[str, Any]) -> Mapping[str, Any]:
        name: str = fields["name"]
        connections: dict[str, ConnectionConfig] = {
            current.name: current for current in fields.get("connections", [])
        }
        drivers: dict[str, DriverConfig] = {
            current.name: current for current in fields.get("drivers", [])
        }
        notifiers: dict[str, DriverConfig] = {
            current.name: current for current in fields.get("notifiers", [])
        }
        components: list[ComponentConfig] = [
            *connections.values(),
            *drivers.values(),
            *notifiers.values(),
        ]

        for component in components:
            for connection_name in component.references.connections.values():
                if connection_name not in connections:
                    raise ValueError(
                        f"invalid reference, connection '{connection_name}' does not exist in unit '{name}'"
                    )

            for driver_name in component.references.drivers.values():
                if driver_name not in drivers:
                    raise ValueError(
                        f"invalid reference, driver '{driver_name}' does not exist in unit '{name}'"
                    )

            for notifier_name in component.references.notifiers.values():
                if notifier_name not in notifiers:
                    raise ValueError(
                        f"invalid reference, notifier '{notifier_name}' does not exist in unit '{name}'"
                    )

        return fields


@dataclass(kw_only=True, frozen=True)
class UserConfig(BaseConfigObject):
    username: NameStr
    email: EmailStr
    meta: frozendict[str, Any] = field(default_factory=frozendict)


warnings.filterwarnings(
    action="ignore",
    message="fields may not start with an underscore",
    category=RuntimeWarning,
    module=sys.modules[__name__].__name__,
)


@dataclass(kw_only=True, frozen=True, config=ConfigDict(underscore_attrs_are_private=True))
class Config(BaseConfigObject):
    server: ServerConfig
    database: DatabaseConfig = Field(discriminator="kind")
    users: frozenlist[UserConfig] = field(default_factory=frozenlist)
    units: frozenlist[UnitConfig] = field(default_factory=frozenlist)

    _path: Path | None = None
    _component_path_cache: dict[ComponentPath, ComponentConfig] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> Config:
        instance = hydrate(cls, data)
        object.__setattr__(instance, "__path__", path)
        return instance

    @property
    def path(self) -> Path | None:
        return self._path

    @validator("units")
    def _validate_units(cls, units: list[UnitConfig]) -> list[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units

    def get_unit(self, path: str | UnitPath) -> UnitConfig | None:
        if isinstance(path, UnitPath):
            path = path.name

        return next(unit for unit in self.units if unit.name == path)

    @overload
    def get_component(self, path: ConnectionPath) -> ConnectionConfig | None:
        ...

    @overload
    def get_component(self, path: DriverPath) -> DriverConfig | None:
        ...

    @overload
    def get_component(self, path: NotifierPath) -> NotifierConfig | None:
        ...

    def get_component(self, path: ComponentPath) -> ComponentConfig | None:
        if path in self._component_path_cache:
            return self._component_path_cache[path]

        component: ComponentConfig | None = None

        if unit := self.get_unit(path.unit):
            match path:
                case ConnectionPath():
                    component = next(
                        (current for current in unit.connections if current.name == path.name), None
                    )
                case DriverPath():
                    component = next(
                        (current for current in unit.drivers if current.name == path.name), None
                    )
                case NotifierPath():
                    component = next(
                        (current for current in unit.notifiers if current.name == path.name), None
                    )

        if component:
            self._component_path_cache[path] = component

        return component
