import asyncio
import itertools
import traceback
from datetime import timedelta
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping, Sequence

import yaml
from pydantic import (
    Field,
    FieldValidationInfo,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
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
from ceres.internal.utilities import get_traceback, lenient_issubclass, show_td
from ceres.loaded import Loader
from ceres.logs import Log
from ceres.result import Fail, Ok, Result
from ceres.schedule import Schedule
from ceres.timing import utc
from ceres.validation import ValidationProblem

if TYPE_CHECKING:
    from ceres.component import Component
else:
    Component = object


class ConfigObject(ImmutableDataObject):
    pass


class _ComponentConfigMixin(ConfigObject):
    name: Name


class JobConfig(ConfigObject):
    name: Name
    action: Name
    args: Mapping[Name, Any] | None = None
    schedule: Schedule = Field(discriminator="kind")

    @model_validator(mode="before")
    def _default_name_to_action(cls, values: dict[str, Any]) -> Any:
        if "name" not in values and "action" in values:
            values["name"] = values["action"]

        return values


class ComponentConfig(Loader, _ComponentConfigMixin):
    cls_path: ClassPath = Field(
        default_factory=lambda: ClassPath("ceres.component.Component"), alias="class"
    )
    jobs: Sequence[JobConfig] = Field(default_factory=list)
    components: Sequence["ComponentConfig"] = Field(default_factory=list)

    def create(self, *, args: Mapping[str, Any] | None = None) -> Component:
        component: Component = super().create(args=args)
        component.__config__ = self
        for job in self.jobs:
            # TODO: Validated job arguments.
            component.add_job(job.name, job.schedule, job.action, job.args)
        return component

    @override
    @classmethod
    def _get_extra_kwarg_names(cls) -> Sequence[str]:
        return [*super()._get_extra_kwarg_names(), "name"]

    @field_validator("cls_path")
    def _validate_cls_path(cls, value: ClassPath) -> ClassPath:
        from ceres.component import Component

        if not lenient_issubclass(value.cls, Component):
            raise ValueError(f"must be a subclass of {Component}")

        return value

    @field_validator("components", check_fields=False)
    def _validate_components(
        cls,
        components: Sequence["ComponentConfig"],
        info: FieldValidationInfo,
    ) -> Sequence["ComponentConfig"]:
        name: str = info.data.get("name", "<ERROR>")
        for component_name, group in itertools.groupby(
            components,
            lambda component: component.name,
        ):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate subcomponent name '{component_name}' in component '{name}'"
                )

        return components


ComponentConfig.model_rebuild()


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
    name: Name = "root"
    service: ServiceConfig | None = None
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="kind")

    @classmethod
    def read(cls, source: Path | Mapping[str, object] | Self) -> "Result[Self, list[ConfigError]]":
        try:
            if isinstance(source, Mapping):
                instance = cls.model_validate(source)
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

                instance = cls.model_validate(data)
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
                instance = cls.model_validate(source)
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

                instance = cls.model_validate(data)
            else:
                instance = source
        except ValidationError as error:
            return Fail([ConfigValidationError(problems=ValidationProblem.extract(error))])

        errors: list[ConfigError] = []

        if ConfigCheckKind.DATABASE in checks:
            database_errors = await cls.__check_database(instance, log_info)
            errors.extend(database_errors)
            if not database_errors:
                log_info("Database configuration is valid.")

        if ConfigCheckKind.COMPONENTS in checks:
            component_errors = await cls.__check_components(instance, log_info)
            errors.extend(component_errors)
            if not component_errors:
                log_info("Component configurations are valid.")

        if errors:
            return Fail(errors)

        return Ok(instance)

    @classmethod
    async def __check_database(
        cls,
        config: Self,
        log: Callable[[object], None],
    ) -> list[ConfigDatabaseError]:
        from ceres.database.database import Database

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
            parent: Component | None,
            component_config: Config | ComponentConfig,
            errors: list[ConfigComponentError],
        ) -> Component | None:
            address = Address.root() if parent is None else parent.address / component_config.name

            if isinstance(component_config, ComponentConfig):
                log(f"Checking '{address}'...")

                try:
                    component = component_config.create()
                except Exception as exception:
                    errors.append(
                        ConfigComponentError(
                            component=address,
                            error=ComponentInitExceptionError(
                                message="an exception occurred while loading this component",
                                traceback=get_traceback(exception),
                            ),
                        )
                    )

                    return None

            if parent is not None:
                parent.add_component(component)

            for subcomponent_config in component_config.components:
                check_component(
                    component,
                    subcomponent_config,
                    errors,
                )

            return component

        errors: list[ConfigComponentError] = []

        root = check_component(None, config, errors)
        if errors or root is None:
            return errors

        for component in root.get_components():
            _, unresolved = component.sync_component_references()
            if unresolved:
                first = next(iter(unresolved))
                target = first.__reference_target__
                errors.append(
                    ConfigComponentError(
                        component=component.address,
                        error=ComponentReferenceInvalidError(
                            message=f"reference to component '{target}' was not found",
                        ),
                    )
                )

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
