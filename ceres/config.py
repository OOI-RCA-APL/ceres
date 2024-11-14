from __future__ import annotations

import os
import ssl
from datetime import timedelta
from pathlib import Path
from re import Pattern
from typing import (
    Annotated,
    Any,
    Literal,
    Mapping,
    Self,
    Sequence,
    TypeVar,
    override,
)

from annotated_types import Ge, Le
from argon2.profiles import RFC_9106_LOW_MEMORY
from pydantic import (
    BaseModel,
    ByteSize,
    ConfigDict,
    Field,
    ImportString,
    IPvAnyAddress,
    NonNegativeInt,
    PositiveInt,
    SecretStr,
    SerializeAsAny,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ceres._internal.lazy import lazy_imports
from ceres._internal.typedecs import __Component__, __Sieve__
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
    ComponentError,
    ComponentInitExceptionError,
    ComponentReferenceInvalidError,
    ComponentValidationError,
    ConfigCombinedError,
    ConfigError,
    ConfigInvalidSourceError,
    ConfigParseError,
    ConfigParseErrorLocation,
    ConfigReadError,
    ConfigValidationError,
    DatabaseError,
    DatabaseUnexpectedError,
    DatabaseUnreachableError,
    Failure,
    ValidationProblem,
)
from ceres.level import Level
from ceres.result import Fail, Ok, Result
from ceres.schedule import Schedule

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres.component import Component
    from ceres.sieve import Sieve


class ConfigObject(ImmutableDataObject):
    pass


class LoggingConfig(ConfigObject):
    level: Level = Level.INFO
    log_events: bool = False
    log_events_level: Level = Level.INFO
    log_messages: bool = False
    log_messages_level: Level = Level.INFO
    log_particles: bool = False
    log_particles_level: Level = Level.INFO
    log_alerts: bool = False
    log_alerts_level: Level | None = None


class JobConfig(ConfigObject):
    name: Name
    action: Name
    arguments: Mapping[Name, Any] | None = None
    schedule: Schedule = Field(discriminator="type")
    retries: NonNegativeInt = 0
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)

    @model_validator(mode="before")
    @classmethod
    def _validate_name_as_action(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            if "action" in data and "name" not in data:
                data = {**data}
                data["name"] = data["action"]

        return data


class SieveConfig(ConfigObject):
    name: Name
    cls: ImportString[type[__Sieve__]] = Field(
        validation_alias="class",
        serialization_alias="class",
    )
    arguments: Mapping[str, Any] = Field(default_factory=dict)
    retries: NonNegativeInt | None = None
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)

    @field_validator("cls")
    def _validate_cls(
        cls,
        value: ImportString[type[Sieve]],
    ) -> ImportString[type[Sieve]]:
        from ceres.sieve import Sieve

        if not issubclass(value, Sieve):
            raise ValueError("class must be a subclass of `ceres.sieve.Sieve`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        self.cls(**self.arguments)
        return self

    def create(self) -> Sieve:
        return self.cls(**self.arguments)


def _get_component_class() -> type[Component]:
    from ceres.component import Component

    return Component


class ComponentConfig(ConfigObject):
    name: Name
    cls: ImportString[type[__Component__]] = Field(
        default_factory=_get_component_class,
        validation_alias="class",
        serialization_alias="class",
    )
    arguments: Mapping[str, Any] = Field(default_factory=dict)
    jobs: Sequence[JobConfig] = Field(default_factory=list)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    sieves: Sequence[SieveConfig] = Field(default_factory=list)
    components: Sequence[ComponentConfig] = Field(default_factory=list)

    @field_validator("cls")
    def _validate_cls(cls, value: ImportString[type[Component]]) -> ImportString[type[Component]]:
        from ceres.component import Component

        if not issubclass(value, Component):
            raise ValueError("class must be a subclass of `ceres.component.Component`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        if "__with_name__" in self.arguments:
            raise ValueError("'__with_name__' is a reserved argument name")

        if "__with_config__" in self.arguments:
            raise ValueError("'__with_config__' is a reserved argument name")

        self.cls(**self.arguments)
        return self

    @field_validator("name")
    def _validate_name(cls, value: Name) -> Name:
        if value == "all":
            raise ValueError("'all' is a disallowed component name")

        return value

    @field_validator("sieves", check_fields=False)
    def _validate_sieves(
        cls,
        sieves: Sequence[SieveConfig],
        info: ValidationInfo,
    ) -> Sequence[SieveConfig]:
        name: str = info.data.get("name", "<ERROR>")
        for sieve_name, group in util.group_by(sieves, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate sieve name '{sieve_name}' in component '{name}'")

        return sieves

    @field_validator("components", check_fields=False)
    def _validate_components(
        cls,
        components: Sequence[ComponentConfig],
        info: ValidationInfo,
    ) -> Sequence[ComponentConfig]:
        name: str = info.data.get("name", "<ERROR>")
        for component_name, group in util.group_by(components, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate component name '{component_name}' in component '{name}'"
                )

        return components

    def create(
        self,
        *,
        parent: Component | None = None,
        address: Address | None = None,
    ) -> Result[Component, list[ComponentError]]:
        instance, errors = self._try_create(parent=parent, address=address)
        if errors or instance is None:
            return Fail(errors)

        return Ok(instance)

    def _try_create(
        self,
        *,
        parent: Component | None = None,
        address: Address | None = None,
    ) -> tuple[Component | None, list[ComponentError]]:
        from ceres.reference import unref

        if address is None:
            if parent is not None:
                address = parent.system.address / self.name
            else:
                address = Address.ROOT

        errors: list[ComponentError] = []
        instance = self._create(address=address, errors=errors)
        if instance is not None and not errors:
            if parent is not None:
                parent.system.attach(instance)

            components = instance.system.get_components(inclusive=True)
            for component in components:
                _, unresolved = component.system.sync_references()
                if unresolved:
                    for reference in unresolved:
                        errors.append(
                            ComponentReferenceInvalidError(
                                address=component.system.address,
                                referenced=reference.__reference_ultimate_target__,
                                expected=reference.__reference_constraint__ or Component,
                                actual=type(unref(reference)),
                            )
                        )

        if instance is not None and errors:
            instance.system.detach()

        return instance, errors

    def _create(self, *, address: Address, errors: list[ComponentError]) -> Component | None:
        try:
            instance = self.cls(
                **self.arguments,
                __with_name__=self.name,
                __with_config__=self,
            )
        except ValidationError as error:
            errors.append(
                ComponentValidationError(
                    address=address,
                    problems=ValidationProblem.extract(error, self.arguments),
                )
            )
            return None
        except Exception as exception:
            errors.append(
                ComponentInitExceptionError(
                    address=address,
                    traceback=util.get_traceback(exception),
                )
            )
            return None

        for child_config in self.components:
            child = child_config._create(
                address=address / child_config.name,
                errors=errors,
            )

            if child is not None:
                instance.system.attach(child, name=child_config.name)

        return instance

    def get_component(self, address: DynamicAddress) -> ComponentConfig | None:
        current = self
        for name in address.names:
            if current is None:
                return None

            current = next((child for child in current.components if child.name == name), None)

        return current

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


ComponentConfig.model_rebuild()


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


class ServerCORSConfig(ConfigObject):
    enabled: bool = True
    allow_origins: str | Sequence[str] = Field(default_factory=list)
    allow_origin_regex: Pattern[str] | None = None
    allow_methods: str | Sequence[str] = "*"
    allow_headers: str | Sequence[str] = "*"
    allow_credentials: bool = True
    expose_headers: str | Sequence[str] = Field(default_factory=list)
    max_age: PositiveInt = 600


class ServerCompressionConfig(ConfigObject):
    enabled: bool = True
    min_size: ByteSize = ByteSize(500)
    zstd: bool = True
    zstd_level: int = Field(default=1, ge=1, le=22)
    brotli: bool = True
    brotli_quality: int = Field(default=4, ge=0, le=11)
    gzip: bool = True
    gzip_level: int = Field(default=1, ge=0, le=9)


class ServerConfig(ConfigObject):
    host: str = "0.0.0.0"  # Bind to IPV4 all addresses by default
    port: int | None = None
    socket: Path | None = None
    ssl: ServerSSLConfig | None = None
    authentication: ServerAuthenticationConfig | None = None
    cors: ServerCORSConfig | None = None
    compression: ServerCompressionConfig | None = None

    @field_validator("host")
    def _validate_host(cls, host: str) -> str:
        util.get_type_adapter(IPvAnyAddress).validate_python(host)
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
    # Using `SerializeAsAny` here to work around Pydantic's union serialization issues dealing with
    # `T | Sequence[T]`. It will currently choose the wrong serializer.
    # See https://github.com/pydantic/pydantic/milestone/13.
    dashboard: SerializeAsAny[Address | Sequence[Address] | None] = None


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
    def all(cls) -> Sequence[ConfigCheckType]:
        return tuple(cls)


class ConfigMeta(ConfigObject):
    model_config = ConfigDict(extra="allow")

    service: ServiceConfig = Field(default_factory=ServiceConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="type")
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def read(cls, source: ConfigSource[Self]) -> Result[Self, ConfigError]:
        import yaml
        from yaml import MarkedYAMLError, YAMLError

        if isinstance(source, cls):
            return Ok(source)

        if isinstance(source, Mapping):
            data = source
        elif isinstance(source, Path):
            try:
                path = source.resolve()
            except Exception:
                return Fail(ConfigReadError(message=f"path '{source}' could not be resolved"))

            try:
                with open(path, "r") as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                return Fail(ConfigReadError(message=f"failed to read file at '{path}'"))
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

                return Fail(ConfigParseError(message=message, location=location))
        else:
            return Fail(ConfigInvalidSourceError(message=f"invalid source type: {type(source)}"))

        try:
            instance = cls.model_validate(data)
        except ValidationError as error:
            return Fail(ConfigValidationError(problems=ValidationProblem.extract(error, data)))

        return Ok(instance)

    @classmethod
    async def load(
        cls,
        config: ConfigSource[Self],
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
    ) -> Result[Self, ConfigError]:
        errors: list[ConfigError] = []

        match cls.read(config):
            case Ok(config):
                pass
            case Fail(error):
                return Fail(error)

        if ConfigCheckType.DATABASE in checks:
            errors.extend(await config._check_database())
        if ConfigCheckType.COMPONENTS in checks:
            errors.extend(await config._check_components())

        if errors:
            return Fail(ConfigCombinedError(errors=errors))

        return Ok(config)

    async def _check_database(self) -> list[DatabaseError]:
        from ceres.database import Database

        database = Database(self.database)
        try:
            async with database.connect():
                pass
        except Failure as failure:
            if isinstance(failure.error, DatabaseError):
                return [failure.error]

            return [
                DatabaseUnexpectedError(
                    message=failure.message,
                )
            ]
        except Exception as exception:
            return [
                DatabaseUnreachableError(
                    message=str(exception),
                )
            ]

        return []

    async def _check_components(self) -> list[ComponentError]:
        return []


class Config(ConfigMeta):
    model_config = ConfigDict(extra="forbid")

    root: ComponentConfig = Field(default_factory=lambda: ComponentConfig(name="root"))

    @model_validator(mode="before")
    @classmethod
    def _validate_before(cls, values: object) -> object:
        if isinstance(values, Mapping):
            values = dict(values)
            if "components" in values:
                if "root" in values:
                    raise ValueError(
                        "cannot have both `root` and `components` defined at base level of config"
                    )

                values["root"] = {"components": values.pop("components")}

        return values

    @model_validator(mode="after")
    def _validate_after(self) -> Self:
        from ceres.roles.interface import Interface

        if self.console.dashboard is not None:
            for address in util.as_sequence(self.console.dashboard):
                component = self.get_component(address)
                if component is None:
                    raise ValueError(f"dashboard component '{address}' does not exist")
                if not issubclass(component.cls, Interface):
                    raise ValueError(
                        f"dashboard component '{address}' must be a subclass of {Interface}, got {component.cls}"
                    )

        return self

    @field_validator("root", mode="before")
    def _validate_root(cls, values: object) -> object:
        if isinstance(values, Mapping):
            if "name" not in values:
                values = {"name": "root", **values}

        return values

    @override
    async def _check_components(self) -> list[ComponentError]:
        match self.root.create():
            case Ok():
                return []
            case Fail(errors):
                return errors

    def get_component(self, address: DynamicAddress) -> ComponentConfig | None:
        return self.root.get_component(address)

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


_TConfig = TypeVar("_TConfig", bound=BaseModel)
ConfigSource = Path | Mapping[str, object] | _TConfig
