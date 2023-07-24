import asyncio
import itertools
import traceback
from datetime import timedelta
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping, Sequence

import yaml
from pydantic import Field, SecretStr, ValidationError, parse_obj_as, validator
from typing_extensions import Self, override
from yaml import MarkedYAMLError, YAMLError

from ceres.address import Address, DynamicAddress
from ceres.data import ClassPath, ImmutableDataObject, Name, NonBlankStr, PositiveTimeDelta
from ceres.errors import (
    ComponentInitExceptionError,
    ComponentReferenceInvalidError,
    ConfigComponentError,
    ConfigDatabaseError,
    ConfigError,
    ConfigParseError,
    ConfigParseErrorLocation,
    ConfigReadError,
    ConfigValidationError,
)
from ceres.internal.utilities import lenient_issubclass, setattr_internal, show_td
from ceres.loaded import Loader
from ceres.logs import Log
from ceres.result import Fail, Ok, Result
from ceres.timing import utc
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = object


class ConfigObject(ImmutableDataObject):
    pass


class _ComponentConfigMixin(ImmutableDataObject):
    name: Name


class ComponentConfig(Loader, _ComponentConfigMixin):
    cls_path: ClassPath = Field(
        default_factory=lambda: ClassPath("ceres.component.Component"), alias="class"
    )
    components: Sequence["ComponentConfig"] = ()

    def create(self, *, args: Sequence[Any] | Mapping[str, Any] | None = None) -> Component:
        component: Component = super().create(args=args)
        component.__config__ = self
        return component

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

    @validator("components", check_fields=False)
    def _validate_components(
        cls,
        components: Sequence["ComponentConfig"],
        values: Mapping[str, Any],
    ) -> Sequence["ComponentConfig"]:
        name: str = values.get("name", "<ERROR>")
        for component_name, group in itertools.groupby(
            components,
            lambda component: component.name,
        ):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate subcomponent name '{component_name}' in component '{name}'"
                )

        return components


ComponentConfig.update_forward_refs()


class ServiceConfig(ConfigObject):
    name: Name
    user: Name | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ServerConfig(ConfigObject):
    port: int | None = None


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


class ConfigCheckKind(str, Enum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> Sequence["ConfigCheckKind"]:
        return tuple(cls)


class Config(ComponentConfig):
    class Config(ComponentConfig.Config):
        underscore_attrs_are_private = True

    name: Name = "root"
    service: ServiceConfig | None = None
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="kind")

    __path: Path | None = None  # type: ignore

    @property
    def path(self) -> Path | None:
        return self.__path

    @classmethod
    def read(cls, source: Path | Mapping[str, object] | Self) -> "Result[Self, list[ConfigError]]":
        try:
            if isinstance(source, Mapping):
                instance = cls.__from_data(source)
            elif isinstance(source, Path):
                try:
                    path = source.resolve()
                except Exception:
                    return Fail([ConfigReadError(message=f"path '{source}' could not be resolved")])

                try:
                    with open(path, "r") as stream:
                        data = yaml.safe_load(stream)
                except OSError:
                    return Fail([ConfigReadError(message=f"failed to read file at '{path}'")])
                except YAMLError as error:
                    message: str | None = None
                    location: ConfigParseErrorLocation | None = None

                    if isinstance(error, MarkedYAMLError):
                        message = error.problem

                        if error.problem_mark:
                            location = ConfigParseErrorLocation(
                                line=error.problem_mark.line,
                                column=error.problem_mark.column,
                            )

                    return Fail(
                        [
                            ConfigParseError(
                                message=message,
                                location=location,
                            )
                        ]
                    )

                instance = cls.__from_data(data, path)
            else:
                instance = source
        except ValidationError as error:
            return Fail([ConfigValidationError(problems=ValidationProblem.extract(error))])

        return Ok(instance)

    @classmethod
    async def load(
        cls,
        source: Path | Mapping[str, object] | Self,
        *,
        checks: Sequence[ConfigCheckKind] = ConfigCheckKind.all(),
        log: Logger | Log | Callable[[object], None] = lambda message: None,
    ) -> "Result[Self, list[ConfigError]]":
        def log_info(message: object) -> None:
            if isinstance(log, Logger | Log):
                log.info(message)
            else:
                log(message)

        try:
            if isinstance(source, Mapping):
                instance = cls.__from_data(source)
            elif isinstance(source, Path):
                try:
                    path = source.resolve()
                except Exception:
                    return Fail([ConfigReadError(message=f"path '{source}' could not be resolved")])

                try:
                    with open(path, "r") as stream:
                        data = yaml.safe_load(stream)
                except OSError:
                    return Fail([ConfigReadError(message=f"failed to read file at '{path}'")])
                except YAMLError as error:
                    message: str | None = None
                    location: ConfigParseErrorLocation | None = None

                    if isinstance(error, MarkedYAMLError):
                        message = error.problem

                        if error.problem_mark:
                            location = ConfigParseErrorLocation(
                                line=error.problem_mark.line,
                                column=error.problem_mark.column,
                            )

                    return Fail(
                        [
                            ConfigParseError(
                                message=message,
                                location=location,
                            )
                        ]
                    )

                instance = cls.__from_data(data, path)
            else:
                instance = source
        except ValidationError as error:
            return Fail([ConfigValidationError(problems=ValidationProblem.extract(error))])

        errors: list[ConfigError] = []

        if ConfigCheckKind.DATABASE in checks:
            errors.extend(await cls.__check_database(instance, log_info))
            log_info("Database configuration is valid.")
        if ConfigCheckKind.COMPONENTS in checks:
            errors.extend(await cls.__check_components(instance, log_info))
            log_info("Component configurations are valid.")

        if errors:
            return Fail(errors)

        return Ok(instance)

    @classmethod
    def __from_data(cls, data: Any, path: Path | None = None) -> Self:
        try:
            instance = parse_obj_as(cls, data)
        except Exception:
            traceback.print_exc()
            raise
        setattr_internal(Config, instance, "__path", path)
        return instance

    @classmethod
    async def __check_database(
        cls,
        config: Self,
        log: Callable[[object], None],
    ) -> list[ConfigDatabaseError]:
        from ceres.database import Database

        log("Checking database configuration...")

        start = utc()
        timeout = config.database.retry.timeout
        interval = config.database.retry.interval

        while True:
            database = Database(config.database)

            try:
                async with database.connect():
                    log("Connected to database successfully.")
                    return []
            except Exception as exception:
                elapsed = utc() - start

                if elapsed > timeout:
                    log(f"Failed to connect to database within {show_td(timeout)}.")
                    await database.dispose()
                    return [
                        ConfigDatabaseError(
                            message="failed to connect to database",
                            exception=traceback.format_exc(),
                        )
                    ]

                log(
                    f"Failed to connect to database, {exception}, {show_td(elapsed)} of "
                    f"{show_td(timeout)} timeout elapsed, retrying in {show_td(interval)}..."
                )
                await database.dispose()
                await asyncio.sleep(interval.total_seconds())
                continue
            finally:
                await database.dispose()

    @classmethod
    async def __check_components(
        cls,
        config: Self,
        log: Callable[[object], None],
    ) -> list[ConfigComponentError]:
        log("Checking component configurations...")

        def check_component(
            address: Address,
            component: Config | ComponentConfig,
            errors: list[ConfigComponentError],
            references: dict[Name, Component],
        ) -> list[ConfigComponentError]:
            if isinstance(component, ComponentConfig):
                log(f"Checking '{address}'...")

                try:
                    instance = component.create()
                except Exception as exception:
                    errors.append(
                        ConfigComponentError(
                            component=address,
                            error=ComponentInitExceptionError(
                                message="an exception occurred while loading this component",
                                traceback=traceback.format_exception(exception),
                            ),
                        )
                    )

                    return errors

                error = instance.assign_references(references)
                if error is not None:
                    errors.append(
                        ConfigComponentError(
                            component=address,
                            error=ComponentReferenceInvalidError(
                                message=error.message,
                            ),
                        )
                    )

                references[component.name] = instance

            subreferences: dict[Name, Component] = {}
            for subcomponent in component.components:
                check_component(address / subcomponent.name, subcomponent, errors, subreferences)

            return errors

        errors: list[ConfigComponentError] = []
        references: dict[Name, Component] = {}

        for component in config.components:
            errors.extend(check_component(Address(component.name), component, errors, references))

        return errors

    def get_component(self, address: DynamicAddress) -> "ComponentConfig | None":
        current = self
        for name in address.names:
            if current is None:
                return None

            current = next((child for child in current.components if child.name == name), None)

        return current

    def get_component_cls(self, address: DynamicAddress) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls_path.cls  # type: ignore
