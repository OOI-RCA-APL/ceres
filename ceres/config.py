import asyncio
import os
import ssl
import traceback
from datetime import timedelta
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Callable, Literal, Mapping, Sequence

import yaml
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
from yaml import MarkedYAMLError, YAMLError

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
from ceres.errors import (
    ConfigDatabaseError,
    ConfigError,
    ConfigParseError,
    ConfigParseErrorLocation,
    ConfigReadError,
    ConfigSystemError,
    ConfigValidationError,
    SystemInitExceptionError,
    SystemReferenceInvalidError,
)
from ceres.internal.utilities import get_traceback, get_type_adapter, group_by, show_td
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


def _get_component_class() -> type[Component]:
    from ceres.component import Component

    return Component


class SystemConfig(ConfigObject):
    name: Name
    component: ImportString[type[Component]] = Field(default_factory=_get_component_class)
    arguments: Mapping[str, Any] = Field(default_factory=dict, validation_alias="args")
    jobs: Sequence[JobConfig] = Field(default_factory=list)
    subsystems: Sequence["SystemConfig"] = Field(default_factory=list)

    @field_validator("name")
    def _validate_name(cls, name: Name) -> Name:
        if name == "all":
            raise ValueError("'all' is disallowed system name")

        return name

    @field_validator("subsystems", check_fields=False)
    def _validate_subsystems(
        cls,
        subsystems: Sequence["SystemConfig"],
        info: ValidationInfo,
    ) -> Sequence["SystemConfig"]:
        name: str = info.data.get("name", "<ERROR>")
        for subsystem_name, group in group_by(
            subsystems,
            lambda subsystem: subsystem.name,
        ):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate subsystem name '{subsystem_name}' in system '{name}'")

        return subsystems


SystemConfig.model_rebuild()


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


class Config(SystemConfig):
    name: Name = "root"
    service: ServiceConfig = Field(default_factory=ServiceConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="type")

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
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        log: Logger | Log | Callable[[object], None] = lambda message: None,
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
        log: Logger | Log | Callable[[object], None] = lambda message: None,
    ) -> "Result[Self, list[ConfigError]]":
        def __log(message: object) -> None:
            if isinstance(log, Logger | Log):
                log.info(message)
            else:
                log(message)

        errors: list[ConfigError] = []

        if ConfigCheckType.DATABASE in checks:
            database_errors = await self.__check_database(__log)
            errors.extend(database_errors)
            if not database_errors:
                __log("Database configuration is valid.")

        if ConfigCheckType.COMPONENTS in checks:
            component_errors = await self.__check_systems(__log)
            errors.extend(component_errors)
            if not component_errors:
                __log("Component configurations appear valid.")

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

    async def __check_systems(self, log: Callable[[object], None]) -> list[ConfigSystemError]:
        log("Checking system configurations...")
        from ceres.system import System

        def check_system(
            parent: System | None,
            system_config: Config | SystemConfig,
            errors: list[ConfigSystemError],
        ) -> System | None:
            address = Address.root() if parent is None else parent.address / system_config.name

            try:
                component = System.from_config(system_config)
                log(f"System '{address}': OK")
            except Exception as exception:
                log(f"System '{address}': ERROR")
                errors.append(
                    ConfigSystemError(
                        system=address,
                        error=SystemInitExceptionError(
                            message="an exception occurred while loading this component",
                            traceback=get_traceback(exception),
                        ),
                    )
                )

                return None

            if parent is not None:
                parent.add(component)

            for subcomponent_config in system_config.subsystems:
                check_system(
                    component,
                    subcomponent_config,
                    errors,
                )

            return component

        errors: list[ConfigSystemError] = []

        root = check_system(None, self, errors)
        if errors or root is None:
            return errors

        for system in root.get_systems():
            _, unresolved = system.sync_references()
            if unresolved:
                first = next(iter(unresolved))
                target = first.__reference_target__
                errors.append(
                    ConfigSystemError(
                        system=system.address,
                        error=SystemReferenceInvalidError(
                            message=f"reference to component at '{target}' was not found",
                        ),
                    )
                )

        return errors

    def get_system(self, address: DynamicAddress) -> "SystemConfig | None":
        current = self
        for name in address.names:
            if current is None:
                return None

            current = next((child for child in current.subsystems if child.name == name), None)

        return current

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        config = self.get_system(address)
        if config is None:
            return None

        return config.component
