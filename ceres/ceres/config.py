import itertools
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal, Mapping, Sequence, Union, cast

from pydantic import Field, SecretStr, parse_obj_as, root_validator, validator
from typing_extensions import Self

from .address import GlobalComponentAddress, UnitAddress
from .data import ImmutableDataObject
from .internal.utilities import NameStr, validate_positive_timedelta
from .result import Ok

if TYPE_CHECKING:
    from .component import Component
else:
    Component = "Component"


class ConfigObject(ImmutableDataObject):
    pass


class ComponentRoleKind(str, Enum):
    CONNECTION = "connection"


class ComponentConfig(ConfigObject):
    name: NameStr
    roles: Sequence[ComponentRoleKind] = Field(default_factory=list)
    component: Union[str, type[Component]]
    parameters: Mapping[NameStr, Any] = Field(default_factory=dict)
    references: Mapping[NameStr, NameStr] = Field(default_factory=dict)

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


class ConcurrencyKind(str, Enum):
    THREAD = "thread"
    PROCESS = "process"


class UnitConfig(ConfigObject):
    name: NameStr
    components: Sequence[ComponentConfig] = Field(default_factory=list)
    concurrency: ConcurrencyKind | None = None

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


class RuntimeConfig(ConfigObject):
    concurrency: ConcurrencyKind = ConcurrencyKind.THREAD


class Config(ConfigObject):
    server: ServerConfig | None = None
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="kind")
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    units: Sequence[UnitConfig] = Field(default_factory=list)

    _path: Path | None = None
    _component_config_cache: dict[GlobalComponentAddress, ComponentConfig] = {}

    @root_validator
    def _validate_root(cls, values: Mapping[str, object]) -> Mapping[str, object]:
        database = cast(DatabaseConfig | None, values.get("database"))
        runtime = cast(RuntimeConfig | None, values.get("runtime"))
        units = cast(Sequence[UnitConfig] | None, values.get("units"))

        if database is None or runtime is None or units is None:
            return values

        if isinstance(database, SQLiteDatabaseConfig) and database.path is None:
            if runtime.concurrency == ConcurrencyKind.PROCESS or any(
                (unit.concurrency or runtime.concurrency) == ConcurrencyKind.PROCESS
                for unit in units
            ):
                raise ValueError(
                    "a temporary SQLite database cannot be used with 'process' based concurrency"
                )

        return values

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> Self:
        instance = parse_obj_as(cls, data)
        object.__setattr__(instance, "_path", path)
        object.__setattr__(instance, "_component_config_cache", {})
        return instance

    @property
    def path(self) -> Path | None:
        return self._path

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
