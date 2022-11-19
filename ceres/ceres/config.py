import itertools
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import Field, PrivateAttr, SecretStr, parse_obj_as, validator
from typing_extensions import Self

from .address import ComponentAddress, UnitAddress
from .data import FrozenDataObject
from .internal.utilities import EmailStr, NameStr, validate_positive_timedelta


class ConfigObject(FrozenDataObject):
    pass


class ComponentConfig(ConfigObject):
    kind: Literal["connection", "driver", "notifier"]
    name: NameStr
    component: str | object
    parameters: dict[str, Any] = Field(default_factory=dict)
    references: dict[NameStr, NameStr] = Field(default_factory=dict)

    @validator("references", pre=True)
    def _validate_references(cls, value: object) -> Any:
        if not isinstance(value, Mapping) and isinstance(value, Iterable):
            return {key: key for key in value}  # type: ignore

        return value  # type: ignore


class ServerConfig(ConfigObject):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseRetryConfig(ConfigObject):
    timeout: timedelta = timedelta(seconds=15)
    interval: timedelta = timedelta(seconds=3)

    @validator("timeout", "interval", pre=True)
    def _validate_timedeltas(cls, value: Any) -> timedelta:
        return validate_positive_timedelta(value)


class BaseDatabaseConfig(ConfigObject):
    kind: DatabaseKind
    engine: dict[str, Any] | None = None
    retry: DatabaseRetryConfig = DatabaseRetryConfig()


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path


class PostgresDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.POSTGRES] = DatabaseKind.POSTGRES
    host: str
    port: int
    database: str
    user: str
    password: SecretStr


DatabaseConfig = SQLiteDatabaseConfig | PostgresDatabaseConfig


class UnitConfig(ConfigObject):
    name: NameStr
    components: list[ComponentConfig] = Field(default_factory=list)

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


class UserConfig(ConfigObject):
    username: NameStr
    email: EmailStr
    meta: dict[str, Any] = Field(default_factory=dict)


class Config(ConfigObject):
    server: ServerConfig
    database: DatabaseConfig = Field(discriminator="kind")
    users: list[UserConfig] = Field(default_factory=list)
    units: list[UnitConfig] = Field(default_factory=list)

    _path: Path | None = PrivateAttr(None)
    _component_config_cache: dict[ComponentAddress, ComponentConfig] = PrivateAttr(
        default_factory=dict
    )

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> Self:
        instance = parse_obj_as(cls, data)
        cls._path = path
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
