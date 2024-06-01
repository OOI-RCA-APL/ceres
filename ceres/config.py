import asyncio
import os
import ssl
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Callable, Literal, Mapping, Sequence

from annotated_types import Ge, Le
from argon2.profiles import RFC_9106_LOW_MEMORY
from pydantic import (
    Field,
    ImportString,
    IPvAnyAddress,
    PositiveInt,
    SecretStr,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from typing_extensions import Self

from ceres._internal.typedecs import __Component__
from ceres._internal.utilities import get_traceback, get_type_adapter, group_by, show_td
from ceres.address import Address, DynamicAddress
from ceres.data import (
    ImmutableDataObject,
    Name,
    NonBlankStr,
    NonEmptyStr,
    PositiveTimeDelta,
    StrEnum,
)
from ceres.database.enums import DatabaseType
from ceres.error import (
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
from ceres.level import Level
from ceres.result import Fail, Ok, Result
from ceres.schedule import Schedule
from ceres.timing import utc
from ceres.validation import ValidationProblem


class ConfigObject(ImmutableDataObject):
    pass


class JobConfig(ConfigObject):
    name: Name
    action: Name
    arguments: Mapping[Name, Any] | None = Field(None, validation_alias="args")
    schedule: Schedule = Field(discriminator="type")

    @model_validator(mode="before")
    def _default_name_to_action(cls, values: dict[str, Any]) -> Any:
        if "name" not in values and "action" in values:
            values["name"] = values["action"]

        return values


class LoggingConfig(ConfigObject):
    level: Level = Level.INFO
    log_events: bool = False
    log_events_level: Level = Level.INFO
    log_messages: bool = False
    log_messages_level: Level = Level.INFO
    log_alerts: bool = False
    log_alerts_level: Level | None = None


def _get_component_class() -> type[__Component__]:
    from ceres.component import Component

    return Component


class NodeConfig(ConfigObject):
    name: Name
    cls: ImportString[type[__Component__]] = Field(
        default_factory=_get_component_class,
        alias="class",
    )
    arguments: Mapping[str, Any] = Field(default_factory=dict, validation_alias="args")
    jobs: Sequence[JobConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    components: Sequence["ComponentConfig"] = Field(default_factory=list)

    @field_validator("cls")
    def _validate_cls(
        cls,
        value: ImportString[type[__Component__]],
    ) -> ImportString[type[__Component__]]:
        from ceres.component import Component

        if not issubclass(value, Component):
            raise ValueError("class must be a subclass of `ceres.component.Component`")

        return value

    @field_validator("name")
    def _validate_name(cls, value: Name) -> Name:
        if value == "all":
            raise ValueError("'all' is a disallowed component name")

        return value

    @field_validator("components", check_fields=False)
    def _validate_children(
        cls,
        components: Sequence["ComponentConfig"],
        info: ValidationInfo,
    ) -> Sequence["ComponentConfig"]:
        name: str = info.data.get("name", "<ERROR>")
        for component_name, group in group_by(
            components,
            lambda subsystem: subsystem.name,
        ):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate component name '{component_name}' in component '{name}'"
                )

        return components


class ComponentConfig(NodeConfig):
    def create(self) -> __Component__:
        component = get_type_adapter(self.cls).validate_python(
            {
                **self.arguments,
                "__with_name__": self.name,
                "__with_config__": self,
            }
        )

        return component


NodeConfig.model_rebuild()


class ServiceConfig(ConfigObject):
    name: Name | None = None
    user: Name | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ServerSSLConfig(ConfigObject):
    key: Path | None = None
    key_password: str | None = None
    cert: Path | None = None
    version: int | None = ssl.PROTOCOL_TLS_SERVER
    ca_certs: Path | None = None


class ServerAuthenticationConfig(ConfigObject):
    secret: NonEmptyStr
    duration: PositiveTimeDelta = timedelta(minutes=30)


class ServerConfig(ConfigObject):
    host: str = "0.0.0.0"  # Bind to IPV4 all addresses by default
    port: int | None = None
    socket: Path | None = None
    ssl: ServerSSLConfig | None = None
    authentication: ServerAuthenticationConfig | None = None

    @field_validator("host")
    def _validate_host(cls, host: str) -> str:
        get_type_adapter(IPvAnyAddress).validate_python(host)
        return host

    @field_validator("socket")
    def _validate_socket(cls, socket: Path | None) -> Path | None:
        if socket is None:
            return None

        try:
            resolved = Path(os.path.normpath(socket)).absolute()
        except Exception:
            return socket

        if len(str(resolved)) > 108:
            raise ValueError(f"resolved socket path {resolved!r} cannot exceed 108 bytes")

        return socket


class ConsoleConfig(ConfigObject):
    title: str | None = None
    favicon: Path | None = None
    dashboard: Address | Sequence[Address] | None = None


class DatabaseRetryConfig(ConfigObject):
    timeout: PositiveTimeDelta = timedelta(seconds=15)
    interval: PositiveTimeDelta = timedelta(seconds=3)


class DatabaseConfigHooks(ConfigObject):
    init: Sequence[str] | None = None
    connect: Sequence[str] | None = None
    close: Sequence[str] | None = None


class HashType(StrEnum):
    BCRYPT = "bcrypt"
    ARGON2 = "argon2"


class BaseHashingConfig(ConfigObject):
    type: HashType


class BCryptHashingConfig(BaseHashingConfig):
    type: Literal[HashType.BCRYPT] = HashType.BCRYPT
    rounds: PositiveInt = 12


class Argon2HashingConfig(BaseHashingConfig):
    type: Literal[HashType.ARGON2] = HashType.ARGON2
    time_cost: PositiveInt = RFC_9106_LOW_MEMORY.time_cost  # 3
    memory_cost: Annotated[int, Ge(8)] = RFC_9106_LOW_MEMORY.memory_cost  # 65536 KiB
    parallelism: PositiveInt = RFC_9106_LOW_MEMORY.parallelism  # 4
    hash_length: Annotated[int, Ge(4), Le(256)] = 32  # True allowed range is 4-32768.
    salt_length: Annotated[int, Ge(8), Le(64)] = 16  # True allowed range is 8-4096.

    @field_validator("parallelism")
    def _validate_memory_cost(cls, value: int, info: ValidationInfo) -> int:
        memory_cost = info.data.get("memory_cost", RFC_9106_LOW_MEMORY.memory_cost)
        if (memory_cost / value) < 8:
            raise ValueError("parallelism must be at least 8 times smaller than memory_cost")

        return value


HashingConfig = BCryptHashingConfig | Argon2HashingConfig


class BaseDatabaseConfig(ConfigObject):
    type: DatabaseType
    hooks: DatabaseConfigHooks = Field(default_factory=DatabaseConfigHooks)
    engine: Mapping[str, Any] = Field(default_factory=dict)
    retry: DatabaseRetryConfig = DatabaseRetryConfig()
    hashing: HashingConfig = Field(default_factory=Argon2HashingConfig, discriminator="type")


class SQLiteDatabaseConfig(BaseDatabaseConfig):
    type: Literal[DatabaseType.SQLITE] = DatabaseType.SQLITE
    path: Path | None = None


class PostgresDatabaseConfig(BaseDatabaseConfig):
    type: Literal[DatabaseType.POSTGRES] = DatabaseType.POSTGRES
    host: NonBlankStr = "localhost"
    port: int = 5432
    database: NonBlankStr
    user: NonBlankStr
    password: SecretStr


DatabaseConfig = SQLiteDatabaseConfig | PostgresDatabaseConfig


class ConfigCheckType(StrEnum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> Sequence["ConfigCheckType"]:
        return tuple(cls)


class Config(ComponentConfig):
    name: Name = "root"
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="type")

    @classmethod
    def read(cls, source: Path | Mapping[str, object] | Self) -> "Result[Self, list[ConfigError]]":
        import yaml
        from yaml import MarkedYAMLError, YAMLError

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
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        log: Callable[[object], Any] = lambda message: None,
    ) -> "Result[Self, list[ConfigError]]":
        match cls.read(source):
            case Ok(instance):
                pass
            case Fail(errors):
                return Fail(errors)

        return await instance.check(checks=checks, log=log)

    async def check(
        self,
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        log: Callable[[object], Any] = lambda message: None,
    ) -> "Result[Self, list[ConfigError]]":
        errors: list[ConfigError] = []

        if ConfigCheckType.DATABASE in checks:
            database_errors = await self.__check_database(log)
            errors.extend(database_errors)
            if not database_errors:
                log("Database configuration is valid.")

        if ConfigCheckType.COMPONENTS in checks:
            component_errors = await self.__check_components(log)
            errors.extend(component_errors)
            if not component_errors:
                log("Component configurations appear valid.")

        if errors:
            return Fail(errors)

        return Ok(self)

    async def __check_database(self, log: Callable[[object], None]) -> list[ConfigDatabaseError]:
        from ceres.database.database import Database

        log("Checking database configuration...")

        start = utc()
        timeout = self.database.retry.timeout
        interval = self.database.retry.interval

        while True:
            database = Database(self.database)

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

    async def __check_components(self, log: Callable[[object], Any]) -> list[ConfigComponentError]:
        log("Checking component configurations...")
        from ceres.component import Component

        def check(
            parent: Component | None,
            component_config: Config | ComponentConfig,
            errors: list[ConfigComponentError],
        ) -> Component | None:
            address = (
                Address.root() if parent is None else parent.system.address / component_config.name
            )

            try:
                component = component_config.create()
                log(f"Component '{address}': OK")
            except Exception as exception:
                log(f"Component '{address}': ERROR")
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
                parent.system.attach(component, name=component_config.name)

            for subcomponent_config in component_config.components:
                check(
                    component,
                    subcomponent_config,
                    errors,
                )

            return component

        errors: list[ConfigComponentError] = []

        root = check(None, self, errors)
        if errors or root is None:
            return errors

        for component in root.system.get_components():
            _, unresolved = component.system.sync_references()
            if unresolved:
                first = next(iter(unresolved))
                target = first.__reference_target__
                errors.append(
                    ConfigComponentError(
                        component=component.system.address,
                        error=ComponentReferenceInvalidError(
                            message=f"reference to component at '{target}' was not found",
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

    def get_component_class(self, address: DynamicAddress) -> type[__Component__] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls
