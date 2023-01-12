import itertools
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, Mapping, Sequence, Union

from pydantic import Field, SecretStr, parse_obj_as, validator
from typing_extensions import Self

from .address import GlobalComponentAddress, UnitAddress
from .data import ImmutableDataObject
from .internal.utilities import NameStr, setattr_internal, validate_positive_timedelta
from .result import Ok
from .schedule import Schedule

if TYPE_CHECKING:
    from .component import Component
else:
    Component = "Component"


class ConfigObject(ImmutableDataObject):
    pass


class ComponentRoleKind(str, Enum):
    CONNECTION = "connection"


class JobConfig(ConfigObject):
    input: Any = None
    schedule: Schedule | None = Field(default=None, discriminator="kind")
    enabled: bool = True


class ComponentConfig(ConfigObject):
    name: NameStr
    roles: Sequence[ComponentRoleKind] = Field(default_factory=list)
    component: Union[str, type[Component]]
    parameters: Mapping[NameStr, Any] = Field(default_factory=dict)
    references: Mapping[NameStr, NameStr] = Field(default_factory=dict)
    jobs: Mapping[NameStr, JobConfig] = Field(default_factory=dict)

    @validator("references", pre=True)
    def _validate_references(cls, value: object) -> object:
        if not isinstance(value, Mapping) and isinstance(value, Iterable):
            return {key: key for key in value}

        return value


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
    engine: Mapping[str, Any] = Field(default_factory=dict)
    retry: DatabaseRetryConfig = DatabaseRetryConfig()


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path | None = None


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
    components: Sequence[ComponentConfig] = Field(default_factory=list)

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


class PathsConfig(ConfigObject):
    data: Path = Field(default=Path("./data"))
    local: Path = Field(default=Path("./local"))


class Config(ConfigObject):
    class Config(ConfigObject.Config):
        underscore_attrs_are_private = True

    server: ServerConfig | None = None
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="kind")
    paths: PathsConfig = Field(default_factory=PathsConfig)
    units: Sequence[UnitConfig] = Field(default_factory=list)

    __path: Path | None = None
    __component_config_cache: dict[GlobalComponentAddress, ComponentConfig] = {}

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> Self:
        instance = parse_obj_as(cls, data)
        setattr_internal(Config, instance, "__path", path)
        setattr_internal(Config, instance, "__component_config_cache", {})
        return instance

    @property
    def path(self) -> Path | None:
        return self.__path

    @validator("units")
    def _validate_units(cls, units: Sequence[UnitConfig]) -> Sequence[UnitConfig]:
        for name, group in itertools.groupby(units, lambda unit: unit.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate unit name '{name}'")

        return units

    def get_unit(self, address: str | UnitAddress) -> UnitConfig | None:
        if isinstance(address, UnitAddress):
            name = address.name
        else:
            name = address

        return next((unit for unit in self.units if unit.name == name), None)

    def get_component(self, address: GlobalComponentAddress) -> ComponentConfig | None:
        if address in self.__component_config_cache:
            return self.__component_config_cache[address]

        component: ComponentConfig | None = None

        if unit := self.get_unit(address.unit):
            component = next(
                (current for current in unit.components if current.name == address.name), None
            )

        if component:
            self.__component_config_cache[address] = component

        return component

    def get_component_cls(self, address: GlobalComponentAddress) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        from .internal.component import load_component_cls

        match load_component_cls(config):
            case Ok(cls):
                return cls
            case _:
                return None


from .component import Component

ComponentConfig.update_forward_refs()
