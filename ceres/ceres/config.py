import itertools
import traceback
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Mapping, Sequence

from pydantic import Field, SecretStr, parse_obj_as, validator
from typing_extensions import Self, override

from ceres.address import Address
from ceres.data import ClassPath, ImmutableDataObject, Name, NonBlankStr, PositiveTimeDelta
from ceres.internal.utilities import lenient_issubclass, setattr_internal
from ceres.loaded import Loader

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = "Component"


class ConfigObject(ImmutableDataObject):
    pass


class _ComponentConfigFields(ImmutableDataObject):
    name: Name


class ComponentConfig(Loader, _ComponentConfigFields):  # type: ignore
    def load(self, *, args: Sequence[Any] | Mapping[str, Any] | None = None) -> Component:
        return super().load(args=args)

    @override
    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return [*super()._get_extra_kwarg_names(), "name"]

    @validator("cls_path")
    def _validate_cls_path(cls, value: ClassPath) -> ClassPath:
        from ceres.component import Component

        if not lenient_issubclass(value.cls, Component):
            raise ValueError(f"must be a subclass of {Component}")

        return value


class DaemonConfig(ConfigObject):
    name: Name
    user: Name | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ServerConfig(ConfigObject):
    port: int
    enable: bool = True


class DatabaseKind(str, Enum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DatabaseRetryConfig(ConfigObject):
    timeout: PositiveTimeDelta = timedelta(seconds=15)
    interval: PositiveTimeDelta = timedelta(seconds=3)


class BaseDatabaseConfig(ConfigObject):
    kind: DatabaseKind
    engine: Mapping[str, Any] = Field(default_factory=dict)
    retry: DatabaseRetryConfig = DatabaseRetryConfig()


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.SQLITE] = DatabaseKind.SQLITE
    path: Path | None = None


class PostgresDatabaseConfig(BaseDatabaseConfig):
    kind: Literal[DatabaseKind.POSTGRES] = DatabaseKind.POSTGRES
    host: NonBlankStr
    port: int
    database: NonBlankStr
    user: NonBlankStr
    password: SecretStr


DatabaseConfig = SQLiteDatabaseConfig | PostgresDatabaseConfig


class UnitConfig(ConfigObject):
    name: Name
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

        return components


class PathsConfig(ConfigObject):
    data: Path = Field(default=Path("./data"))
    local: Path = Field(default=Path("./local"))


class Config(ConfigObject):
    class Config(ConfigObject.Config):
        underscore_attrs_are_private = True

    daemon: DaemonConfig | None = None
    server: ServerConfig | None = None
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="kind")
    paths: PathsConfig = Field(default_factory=PathsConfig)
    units: Sequence[UnitConfig] = Field(default_factory=list)

    __path: Path | None = None  # type: ignore
    __component_config_cache: dict[Address, ComponentConfig] = {}  # type: ignore

    @classmethod
    def from_data(cls, data: Any, path: Path | None = None) -> Self:
        try:
            instance = parse_obj_as(cls, data)
        except Exception:
            traceback.print_exc()
            raise
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

    def get_unit(self, name: Name) -> UnitConfig | None:
        return next((unit for unit in self.units if unit.name == name), None)

    def get_component(self, address: Address) -> ComponentConfig | None:
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

    def get_component_cls(self, address: Address) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls_path.cls  # type: ignore
