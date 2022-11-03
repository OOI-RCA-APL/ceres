import itertools
import sys
import warnings
from dataclasses import field
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import ConfigDict, Field, SecretStr, validator

from .address import ComponentAddress, UnitAddress
from .internal.utilities import (
    EmailStr,
    NameStr,
    frozendict,
    frozenlist,
    hydrate,
    validate_positive_timedelta,
)
from .utilities import vdc


@vdc(frozen=True)
class BaseConfigObject:
    pass


@vdc(frozen=True)
class ComponentConfig(BaseConfigObject):
    kind: Literal["connection", "driver", "notifier"]
    name: NameStr
    component: str | object
    parameters: frozendict[str, Any] = field(default_factory=frozendict)
    references: frozendict[NameStr, NameStr] = field(default_factory=frozendict)

    @validator("references", pre=True)
    def _validate_references(cls, value: object) -> Any:
        if not isinstance(value, Mapping) and isinstance(value, Iterable):
            return {key: key for key in value}  # type: ignore

        return value  # type: ignore


@vdc(frozen=True)
class ServerConfig(BaseConfigObject):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


@vdc(frozen=True)
class DatabaseRetryConfig(BaseConfigObject):
    timeout: timedelta = timedelta(seconds=15)
    interval: timedelta = timedelta(seconds=3)

    @validator("timeout", "interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


@vdc(frozen=True)
class BaseDatabaseConfig(BaseConfigObject):
    kind: DatabaseKind
    engine: frozendict[str, Any] | None = None
    retry: DatabaseRetryConfig = field(default_factory=DatabaseRetryConfig)


@vdc(frozen=True)
class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path


@vdc(frozen=True)
class PostgresDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.POSTGRES] = DatabaseKind.POSTGRES
    host: str
    port: int
    database: str
    user: str
    password: SecretStr


DatabaseConfig = SQLiteDatabaseConfig | PostgresDatabaseConfig


@vdc(frozen=True)
class UnitConfig(BaseConfigObject):
    name: NameStr
    components: frozenlist[ComponentConfig] = field(default_factory=frozenlist)

    @validator("components")
    def _validate_components(
        cls,
        components: Sequence[ComponentConfig],
        values: Mapping[str, Any],
    ) -> Sequence[ComponentConfig]:
        name: str = values.get("name", "<ERROR>")
        for component_name, group in itertools.groupby(
            components,
            lambda component: component.name,
        ):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate component name '{component_name}' in unit '{name}'")

        mapping: dict[str, ComponentConfig] = {current.name: current for current in components}

        for component in components:
            for component_name in component.references.values():
                if component_name not in mapping:
                    raise ValueError(
                        f"invalid reference, component '{component_name}' does not exist in unit '{name}'"
                    )

        return components


@vdc(frozen=True)
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


@vdc(
    kw_only=True,
    frozen=True,
    config=ConfigDict(underscore_attrs_are_private=True),
)
class Config(BaseConfigObject):
    server: ServerConfig
    database: DatabaseConfig = Field(discriminator="kind")
    users: frozenlist[UserConfig] = field(default_factory=frozenlist)
    units: frozenlist[UnitConfig] = field(default_factory=frozenlist)

    _path: Path | None = None
    _component_config_cache: dict[ComponentAddress, ComponentConfig] = field(default_factory=dict)

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> "Config":
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

    def get_unit(self, address: str | UnitAddress) -> UnitConfig | None:
        if isinstance(address, UnitAddress):
            address = address.name

        return next(unit for unit in self.units if unit.name == address)

    def get_component(self, address: ComponentAddress) -> ComponentConfig | None:
        if address in self._component_config_cache:
            return self._component_config_cache[address]

        component: ComponentConfig | None = None

        if unit := self.get_unit(address.unit):
            component = next(
                (current for current in unit.components if current.name == address.name), None
            )

        if component:
            self._component_config_cache[address] = component

        return component
