import ssl
from abc import abstractmethod
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from re import Pattern
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    Self,
    TypeAlias,
    override,
)

from pydantic import (
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

from ceres._internal import util
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import AlertFilter
from ceres.data import (
    DataObject,
    MaybeSequence,
    Name,
    NonBlankStr,
    NonEmptyStr,
    PositiveTimeDelta,
    StrEnum,
    to_kwargs,
    validate,
)
from ceres.database import DatabaseType
from ceres.entity import EntityType
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
from ceres.logs import LogEntryFilter
from ceres.message import MessageFilter
from ceres.particle import ParticleFilter
from ceres.result import Fail, Ok, Result
from ceres.schedule import ScheduleExpr

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.connection import Connection
    from ceres.engine import Engine
    from ceres.sieve import FunctionalSieve, Sieve
else:
    Sieve = Any
    Component = Any


class LoggingConfig(DataObject):
    output: Level = Level.INFO
    store: Level = Level.DEBUG
    events: bool | Level = True
    messages: bool | Level = False
    particles: bool | Level = False
    alerts: bool | Level = False


class JobConfig(DataObject):
    name: Name
    action: Name
    arguments: Mapping[Name, Any] | None = None
    schedule: ScheduleExpr
    retries: NonNegativeInt = 0
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)

    @model_validator(mode="before")
    @to_kwargs
    @classmethod
    def _validate_name_as_action(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            if "action" in data and "name" not in data:
                data = {**data}
                data["name"] = data["action"]

        return data


class ConnectionConfig(DataObject):
    name: Name
    if TYPE_CHECKING:
        cls: ImportString[type[Connection]]
    else:
        cls: ImportString[object] = Field(
            validation_alias="class",
            serialization_alias="class",
        )
    arguments: Mapping[str, Any] = Field(default_factory=dict)

    @field_validator("cls")
    def _validate_cls(cls, value: object) -> ImportString[type[Connection]]:
        from ceres.connection import Connection

        if not isinstance(value, type) or not issubclass(value, Connection):
            raise ValueError("`class` must be a subclass of `ceres.connection.Connection`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        validate(self.arguments, self.cls)
        return self

    def create(self) -> Connection:
        return validate(self.arguments, self.cls)


class _PrunerConfig[TFilter](DataObject):
    name: Name
    prunes: EntityType
    schedule: ScheduleExpr
    filter: TFilter


class MessagePrunerConfig(_PrunerConfig[MessageFilter]):
    prunes: Literal[EntityType.MESSAGE] = EntityType.MESSAGE


class ParticlePrunerConfig(_PrunerConfig[ParticleFilter]):
    prunes: Literal[EntityType.PARTICLE] = EntityType.PARTICLE


class AlertPrunerConfig(_PrunerConfig[AlertFilter]):
    prunes: Literal[EntityType.ALERT] = EntityType.ALERT


class LogEntryPrunerConfig(_PrunerConfig[LogEntryFilter]):
    prunes: Literal[EntityType.LOG_ENTRY] = EntityType.LOG_ENTRY


PrunerConfig: TypeAlias = (
    MessagePrunerConfig | ParticlePrunerConfig | AlertPrunerConfig | LogEntryPrunerConfig
)


class _SieveConfig(DataObject):
    type: Literal["class", "method"]
    name: Name
    retries: NonNegativeInt | None = None
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)
    filter: MessageFilter | None = None

    @abstractmethod
    def create(self, component: Component) -> Sieve: ...


class ClassSieveConfig(_SieveConfig):
    type: Literal["class"] = "class"
    if TYPE_CHECKING:
        cls: ImportString[type[Sieve]]
    else:
        cls: ImportString[object] = Field(
            validation_alias="class",
            serialization_alias="class",
        )

    arguments: Mapping[str, Any] = Field(default_factory=dict)

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
        validate(self.arguments, self.cls)
        return self

    @override
    def create(self, component: Component) -> Sieve:
        return validate(self.arguments, self.cls)


class MethodSieveConfig(_SieveConfig):
    type: Literal["method"] = "method"
    method: Name

    @override
    def create(self, component: Component) -> FunctionalSieve:
        from ceres.sieve import FunctionalSieve

        method = getattr(component, self.method)
        return FunctionalSieve(function=method)


SieveConfig: TypeAlias = ClassSieveConfig | MethodSieveConfig


def _get_component_class() -> type[Component]:
    from ceres.component import Component

    return Component


class ComponentConfig(DataObject):
    name: Name
    cls: ImportString[type[Component]] = Field(
        default_factory=_get_component_class,
        validation_alias="class",
        serialization_alias="class",
    )
    arguments: dict[str, Any] = Field(default_factory=dict)
    logging: LoggingConfig | None = None
    connections: list[ConnectionConfig] = Field(default_factory=list)
    sieves: list[SieveConfig] = Field(default_factory=list)
    jobs: list[JobConfig] = Field(default_factory=list)
    pruners: list[Annotated[PrunerConfig, Field(discriminator="prunes")]] = Field(
        default_factory=list
    )
    components: list[ComponentConfig] = Field(default_factory=list)

    @field_validator("cls")
    def _validate_cls(cls, value: ImportString[type]) -> ImportString[type[Component]]:
        from ceres.component import Component

        if not issubclass(value, Component):
            raise ValueError("class must be a subclass of `ceres.component.Component`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        for argument in self.arguments:
            if argument.startswith("__with"):
                raise ValueError(f"arguments starting with '__with' are reserved, got '{argument}'")

        validate(self.arguments, self.cls)
        return self

    @field_validator("name")
    def _validate_name(cls, value: Name) -> Name:
        if value == "all":
            raise ValueError("'all' is a disallowed component name")

        return value

    @field_validator("pruners", check_fields=False)
    def _validate_pruners(
        cls,
        pruners: list[PrunerConfig],
        info: ValidationInfo,
    ) -> list[PrunerConfig]:
        name: str = info.data.get("name", "<ERROR>")
        for pruner_name, group in util.group_by(pruners, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate pruner name '{pruner_name}' in component '{name}'")

        return pruners

    @field_validator("sieves", check_fields=False)
    def _validate_sieves(
        cls,
        sieves: list[SieveConfig],
        info: ValidationInfo,
    ) -> list[SieveConfig]:
        name: str = info.data.get("name", "<ERROR>")
        for sieve_name, group in util.group_by(sieves, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate sieve name '{sieve_name}' in component '{name}'")

        return sieves

    @field_validator("components", check_fields=False)
    def _validate_components(
        cls,
        components: list[ComponentConfig],
        info: ValidationInfo,
    ) -> list[ComponentConfig]:
        name: str = info.data.get("name", "<ERROR>")
        for component_name, group in util.group_by(components, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate component name '{component_name}' in component '{name}'"
                )

        return components

    def create(
        self,
        container: Component | ComponentSystem | Engine | None = None,
    ) -> Result[Component, list[ComponentError]]:
        container = util.as_component_system(container) or util.as_engine(container)
        instance, errors = self._try_create(container)
        if errors or instance is None:
            return Fail(errors)

        return Ok(instance)

    def _try_create(
        self,
        container: ComponentSystem | Engine | None,
    ) -> tuple[Component | None, list[ComponentError]]:
        from ceres.reference import unref

        parent = util.as_component_system(container)
        if parent is not None:
            address = parent.address / self.name
        else:
            address = Address.ROOT

        errors: list[ComponentError] = []
        instance = self._create(
            address=address,
            container=container,
            errors=errors,
        )

        if instance is not None and not errors:
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

        if errors and instance is not None:
            instance.system.detach()

        return instance, errors

    def _create(
        self,
        *,
        address: Address,
        container: ComponentSystem | Engine | None,
        errors: list[ComponentError],
    ) -> Component | None:
        try:
            instance = validate(
                {
                    **self.arguments,
                    "__with_name__": self.name,
                    "__with_config__": self,
                    "__with_container__": container,
                },
                self.cls,
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
            child_config._create(
                address=address / child_config.name,
                container=instance.system,
                errors=errors,
            )

        assert instance.system.container is container
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


class ServiceConfig(DataObject):
    name: Name | None = None
    user: Name | None = None
    stdout: Path | None = None
    stderr: Path | None = None


class ServerSSLConfig(DataObject):
    key: Path | None = None
    key_password: str | None = None
    cert: Path | None = None
    version: int | None = ssl.PROTOCOL_TLS_SERVER
    ca_certs: Path | None = None


class ServerAuthenticationConfig(DataObject):
    secret: NonEmptyStr
    duration: PositiveTimeDelta = timedelta(minutes=30)


class ServerCorsConfig(DataObject):
    enabled: bool = True
    allow_origins: MaybeSequence[str] = Field(default_factory=list)
    allow_origin_regex: Pattern[str] | None = None
    allow_methods: MaybeSequence[str] = "*"
    allow_headers: MaybeSequence[str] = "*"
    allow_credentials: bool = True
    expose_headers: MaybeSequence[str] = Field(default_factory=list)
    max_age: PositiveInt = 600


class ServerCompressionConfig(DataObject):
    enabled: bool = True
    min_size: ByteSize = ByteSize(500)
    zstd: bool = True
    zstd_level: int = Field(default=1, ge=1, le=22)
    brotli: bool = True
    brotli_quality: int = Field(default=4, ge=0, le=11)
    gzip: bool = True
    gzip_level: int = Field(default=1, ge=0, le=9)


class ServerConfig(DataObject):
    host: str = "0.0.0.0"  # Bind to IPV4 all addresses by default
    port: int | None = None
    ssl: ServerSSLConfig | None = None
    authentication: ServerAuthenticationConfig | None = None
    cors: ServerCorsConfig | None = None
    compression: ServerCompressionConfig | None = None

    @field_validator("host")
    def _validate_host(cls, host: str) -> str:
        validate(host, IPvAnyAddress)
        return host


class ConsoleConfig(DataObject):
    title: str | None = None
    favicon: Path | None = None
    # Using `SerializeAsAny` here to work around Pydantic's union serialization issues dealing with
    # `T | Sequence[T]`. It will currently choose the wrong serializer.
    # See https://github.com/pydantic/pydantic/milestone/13.
    dashboard: SerializeAsAny[MaybeSequence[Address] | None] = None


class DatabaseRetryConfig(DataObject):
    timeout: PositiveTimeDelta = timedelta(seconds=15)
    interval: PositiveTimeDelta = timedelta(seconds=3)


class DatabaseConfigHooks(DataObject):
    init: list[str] | None = None
    connect: list[str] | None = None
    close: list[str] | None = None


class HashType(StrEnum):
    BCRYPT = "bcrypt"
    ARGON2 = "argon2"


class _HashingConfig(DataObject):
    type: HashType


class BCryptHashingConfig(_HashingConfig):
    type: Literal[HashType.BCRYPT] = HashType.BCRYPT
    rounds: int = Field(default=12, ge=4)


class Argon2HashingConfig(_HashingConfig):
    type: Literal[HashType.ARGON2] = HashType.ARGON2
    # These default values are taken from `argon2.profiles.RFC_9106_LOW_MEMORY`.
    time_cost: PositiveInt = 3
    memory_cost: int = Field(default=65536, ge=8)  # Default is 64 MiB.
    parallelism: PositiveInt = 4
    hash_length: int = Field(default=32, ge=4, le=256)  # True allowed range is 4-32768.
    salt_length: int = Field(default=16, ge=8, le=64)  # True allowed range is 8-4096.

    @field_validator("parallelism")
    def _validate_memory_cost(cls, value: int, info: ValidationInfo) -> int:
        memory_cost = info.data.get("memory_cost", 65536)
        if (memory_cost / value) < 8:
            raise ValueError("parallelism must be at least 8 times smaller than memory_cost")

        return value


HashingConfig: TypeAlias = BCryptHashingConfig | Argon2HashingConfig


class _DatabaseConfig(DataObject):
    type: DatabaseType
    hooks: DatabaseConfigHooks = Field(default_factory=DatabaseConfigHooks)
    engine: dict[str, Any] = Field(default_factory=dict)
    hashing: HashingConfig = Field(default_factory=Argon2HashingConfig, discriminator="type")
    query: dict[str, MaybeSequence[str]] | None = None


class SQLiteDatabaseConfig(_DatabaseConfig):
    type: Literal[DatabaseType.SQLITE] = DatabaseType.SQLITE
    path: Path | None = None


class PostgresDatabaseConfig(_DatabaseConfig):
    type: Literal[DatabaseType.POSTGRES] = DatabaseType.POSTGRES
    host: NonBlankStr
    port: NonNegativeInt | None = None
    database: NonBlankStr
    user: NonBlankStr
    password: SecretStr | None = None


DatabaseConfig: TypeAlias = SQLiteDatabaseConfig | PostgresDatabaseConfig


class ConfigCheckType(StrEnum):
    DATABASE = "database"
    COMPONENTS = "components"

    @classmethod
    def all(cls) -> tuple[ConfigCheckType, ...]:
        return tuple(cls)


class ConfigMeta(DataObject, config=ConfigDict(extra="allow")):
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
                with open(path) as stream:
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
            instance = validate(data, cls)
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


class Config(ConfigMeta, config={"extra": "forbid"}):
    root: ComponentConfig = Field(default_factory=lambda: ComponentConfig(name="root"))

    @model_validator(mode="before")
    @to_kwargs
    @classmethod
    def _validate_before(cls, values: object | Mapping[str, Any]) -> object:
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
        from ceres.interface import Interface

        if self.console.dashboard is not None:
            for address in util.seq(self.console.dashboard):
                component = self.get_component(address)
                if component is None:
                    raise ValueError(f"dashboard component '{address}' does not exist")
                if not issubclass(component.cls, Interface):
                    raise ValueError(
                        f"dashboard component '{address}' must be a subclass of {Interface}, got {component.cls}"
                    )

        return self

    @field_validator("root", mode="before")
    @to_kwargs
    def _validate_root(cls, values: object | Mapping[str, Any]) -> object:
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

    def get_components(
        self,
        address: AddressSelector | None = None,
    ) -> dict[Address, ComponentConfig]:
        configs: dict[Address, ComponentConfig] = {}

        def recurse(config: ComponentConfig, address: Address, selector: AddressSelector | None):
            if not selector or selector.matches(address, Address.ROOT):
                configs[address] = config

            for child in config.components:
                recurse(child, address / child.name, selector)

        recurse(self.root, Address.ROOT, address)

        return configs

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


type ConfigSource[T: DataObject] = Path | Mapping[str, object] | T
