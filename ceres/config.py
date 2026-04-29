import ssl
from abc import abstractmethod
from collections.abc import Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from re import Pattern
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeAlias, override

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

from ceres.__internal__.utilities.collections import group_by, seq, uniq
from ceres.__internal__.utilities.typing import as_component_system, as_engine
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import AlertFilter
from ceres.constants import DEFAULT_BUFFER_DROP, DEFAULT_BUFFER_SIZE
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
    ComponentCombinedError,
    ComponentError,
    ComponentInitExceptionError,
    ComponentReferenceInvalidError,
    ComponentUnexpectedError,
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
    trace,
)
from ceres.level import Level
from ceres.logs import LogEntryFilter
from ceres.message import MessageFilter
from ceres.particle import ParticleFilter
from ceres.schedule import ScheduleExpr

if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.connection import Connection, ConnectionField
    from ceres.engine import Engine
    from ceres.sieve import FunctionSieve, Sieve
else:
    Sieve = Any
    Component = Any
    Connection = Any
    ConnectionField = Any

__all__ = [
    "Config",
]


class LoggingConfig(DataObject):
    """Per-component or per-engine logging configuration.

    Each field controls a different sink, `output` and `store` set minimum levels for
    the streamed and persisted log streams, the boolean-or-level fields enable optional
    logging of specific record types and accept either a level (enable at that level) or
    a boolean (enable at the default level when `True`, disable when `False`).
    """

    output: Level = Level.INFO
    """Minimum severity that reaches the engine's streamed log output."""

    store: Level = Level.DEBUG
    """Minimum severity persisted to the engine's log store."""

    events: bool | Level = True
    """Whether to log events, or the minimum severity to log them at."""

    messages: bool | Level = False
    """Whether to log raw connection messages, or the minimum severity to log them at."""

    particles: bool | Level = False
    """Whether to log parsed particles, or the minimum severity to log them at."""

    alerts: bool | Level = False
    """Whether to log alerts, or the minimum severity to log them at."""


class JobConfig(DataObject):
    """Configuration for a scheduled job that invokes a component action.

    A job names the action to call, the schedule on which to call it, and how many
    retries to attempt on failure. Jobs are typically declared inline in a component's
    configuration but can also be added at runtime via `system.jobs.add`.
    """

    name: Name
    """Unique job name within the owning component."""

    action: Name
    """Name of the action to invoke on the component."""

    arguments: Mapping[Name, Any] | None = None
    """Keyword arguments passed to the action when it is invoked."""

    schedule: ScheduleExpr
    """Schedule controlling when the job runs."""

    retries: NonNegativeInt = 0
    """Number of additional attempts if the action raises."""

    retry_delay: PositiveTimeDelta = timedelta(seconds=5)
    """Delay between retry attempts."""

    @model_validator(mode="before")
    @to_kwargs
    @classmethod
    def _validate_name_as_action(cls, data: Any) -> Any:
        # Allow `name` to be omitted when `action` is given, the action name is a sensible
        # default identifier for a job that targets it.
        if isinstance(data, Mapping):
            if "action" in data and "name" not in data:
                data = {**data}
                data["name"] = data["action"]

        return data


def _get_connection_class() -> type[Connection]:
    from ceres.connection import Connection

    return Connection


class ConnectionConfig(DataObject):
    """Configuration for a single named connection on a component.

    The `class` field selects a `Connection` subclass to instantiate, `arguments` are
    validated against that class's schema before instantiation so that misconfiguration
    surfaces at config-load time rather than at component start.
    """

    name: Name
    """Connection name, unique within the owning component."""

    cls: ImportString[type[Connection]] = Field(
        default_factory=_get_connection_class,
        validation_alias="class",
        serialization_alias="class",
    )
    """`Connection` subclass to instantiate, defaults to the base `Connection` class."""

    arguments: Mapping[str, Any] = Field(default_factory=dict)
    """Keyword arguments passed to the connection constructor."""

    @field_validator("cls")
    def _validate_cls(cls, value: object) -> ImportString[type[Connection]]:
        from ceres.connection import Connection

        if not isinstance(value, type) or not issubclass(value, Connection):
            raise ValueError("`class` must be a subclass of `ceres.connection.Connection`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        # Eagerly validate constructor arguments so configuration errors surface during
        # config load rather than at connection instantiation time.
        validate(self.cls, self.arguments)
        return self

    def create(self) -> Connection:
        """Instantiate the configured `Connection`."""
        return validate(self.cls, self.arguments)


class _PrunerConfig[TFilter](DataObject):
    name: Name
    prunes: EntityType
    schedule: ScheduleExpr
    filter: TFilter


class MessagePrunerConfig(_PrunerConfig[MessageFilter]):
    """Pruner configuration that periodically deletes matching `Message` records."""

    prunes: Literal[EntityType.MESSAGE] = EntityType.MESSAGE


class ParticlePrunerConfig(_PrunerConfig[ParticleFilter]):
    """Pruner configuration that periodically deletes matching `Particle` records."""

    prunes: Literal[EntityType.PARTICLE] = EntityType.PARTICLE


class AlertPrunerConfig(_PrunerConfig[AlertFilter]):
    """Pruner configuration that periodically deletes matching `Alert` records."""

    prunes: Literal[EntityType.ALERT] = EntityType.ALERT


class LogEntryPrunerConfig(_PrunerConfig[LogEntryFilter]):
    """Pruner configuration that periodically deletes matching `LogEntry` records."""

    prunes: Literal[EntityType.LOG_ENTRY] = EntityType.LOG_ENTRY


PrunerConfig: TypeAlias = (
    MessagePrunerConfig | ParticlePrunerConfig | AlertPrunerConfig | LogEntryPrunerConfig
)
"""Discriminated union of pruner configurations, dispatched by the `prunes` field."""


class _SieveConfig(DataObject):
    type: Literal["class", "method"]
    name: Name
    stored: bool = True
    retries: NonNegativeInt | None = None
    retry_delay: PositiveTimeDelta = timedelta(seconds=5)
    filter: MessageFilter | None = None
    buffer_size: ByteSize | None = Field(default=None, gt=0)
    buffer_drop: ByteSize | None = Field(default=None, gt=0)

    @abstractmethod
    def create(self, component: Component) -> Sieve:
        """Instantiate the configured `Sieve` for `component`."""
        ...


class ClassSieveConfig(_SieveConfig):
    """Sieve configuration that instantiates a `Sieve` subclass directly."""

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
        validate(self.cls, self.arguments)
        return self

    @override
    def create(self, component: Component) -> Sieve:
        """Instantiate the configured `Sieve` subclass with the stored arguments.

        Args:
            component: The owning component. Not used directly by `ClassSieveConfig`,
                but required by the `_SieveConfig` interface.

        Returns:
            A validated instance of `self.cls`.
        """
        return validate(self.cls, self.arguments)


class MethodSieveConfig(_SieveConfig):
    """Sieve configuration that wraps a method on the owning component as a `FunctionSieve`."""

    type: Literal["method"] = "method"
    method: Name
    """Name of the method on the component to wrap."""

    connections: Sequence[Name] | None = None
    """Connections whose buffer settings should influence this sieve's buffering."""

    @override
    def create(self, component: Component) -> FunctionSieve:
        """Wrap the named method on `component` as a `FunctionSieve`.

        Buffer sizes are resolved by taking the maximum of any explicitly configured
        value and the buffer sizes of associated connections, falling back to the
        project defaults when nothing is specified.

        Args:
            component: The component whose method should be wrapped.

        Returns:
            A `FunctionSieve` backed by the resolved method and buffer settings.
        """
        from ceres.sieve import FunctionSieve

        method = getattr(component, self.method)
        applied_buffer_size = self.buffer_size
        applied_buffer_drop = self.buffer_drop

        # Combine explicitly listed connections with any connection referenced by the
        # filter, the sieve's effective buffer settings derive from the union.
        connection_names: list[str] = list(self.connections or ())
        if self.filter and self.filter.connection:
            connection_names.extend(seq(self.filter.connection))

        # When buffer sizes are not pinned on the sieve, scale them up to the largest
        # buffer of any associated connection so that bursts from a fast connection do
        # not overflow the sieve's queue.
        for connection_name in uniq(connection_names):
            connection = component.system.connections.get(connection_name)
            if connection is None:
                continue

            if self.buffer_size is None:
                if applied_buffer_size is None or connection.buffer_size > applied_buffer_size:
                    applied_buffer_size = connection.buffer_size
            if self.buffer_drop is None:
                if applied_buffer_drop is None or connection.buffer_drop > applied_buffer_drop:
                    applied_buffer_drop = connection.buffer_drop

        if applied_buffer_size is None:
            applied_buffer_size = DEFAULT_BUFFER_SIZE
        if applied_buffer_drop is None:
            applied_buffer_drop = DEFAULT_BUFFER_DROP

        return FunctionSieve(
            function=method,
            buffer_size=applied_buffer_size,
            buffer_drop=applied_buffer_drop,
        )


SieveConfig: TypeAlias = ClassSieveConfig | MethodSieveConfig
"""Discriminated union of sieve configurations, dispatched by the `type` field."""


def _get_component_class() -> type[Component]:
    from ceres.component import Component

    return Component


class ComponentConfig(DataObject):
    """Configuration tree for a single component and any nested child components.

    A `ComponentConfig` is the unit users edit in YAML, it selects the component class to
    instantiate, supplies constructor arguments, and declares the component's connections,
    sieves, jobs, pruners, and child components.
    """

    name: Name
    """Component name, unique within its parent and used to build the component address."""

    cls: ImportString[type[Component]] = Field(
        default_factory=_get_component_class,
        validation_alias="class",
        serialization_alias="class",
    )
    """`Component` subclass to instantiate, defaults to the base `Component` class."""

    arguments: dict[str, Any] = Field(default_factory=dict)
    """Keyword arguments passed to the component constructor."""

    logging: LoggingConfig | None = None
    """Per-component logging overrides, falls back to the engine config when omitted."""

    connections: list[ConnectionConfig] = Field(default_factory=list)
    """Connections owned by this component."""

    sieves: list[SieveConfig] = Field(default_factory=list)
    """Sieves owned by this component."""

    jobs: list[JobConfig] = Field(default_factory=list)
    """Scheduled jobs owned by this component."""

    pruners: list[Annotated[PrunerConfig, Field(discriminator="prunes")]] = Field(
        default_factory=list
    )
    """Pruners owned by this component."""

    components: list[ComponentConfig] = Field(default_factory=list)
    """Nested child component configurations."""

    @field_validator("cls")
    def _validate_cls(cls, value: ImportString[type]) -> ImportString[type[Component]]:
        from ceres.component import Component

        if not issubclass(value, Component):
            raise ValueError("class must be a subclass of `ceres.component.Component`")

        return value

    @model_validator(mode="after")
    def _validate_arguments(self) -> Self:
        # Reserve the `__with` prefix for internal injection of name, config, and container
        # during component construction, user-supplied arguments must not collide.
        for argument in self.arguments:
            if argument.startswith("__with"):
                raise ValueError(f"arguments starting with '__with' are reserved, got '{argument}'")

        validate(self.cls, self.arguments)
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
        for pruner_name, group in group_by(pruners, lambda current: current.name):
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
        for sieve_name, group in group_by(sieves, lambda current: current.name):
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
        for component_name, group in group_by(components, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(
                    f"duplicate component name '{component_name}' in component '{name}'"
                )

        return components

    def create(
        self,
        container: Component | ComponentSystem | Engine | None = None,
    ) -> Component:
        """Instantiate this component and any nested children inside `container`.

        Args:
            container: The parent component, component system, or engine to attach
                the new component to. Pass `None` to construct a root component.

        Returns:
            The instantiated component, fully wired with children and references resolved.

        Raises:
            Failure: Wraps a `ComponentCombinedError` describing every error encountered
                while constructing the component tree.
        """
        container = as_component_system(container) or as_engine(container)
        instance, errors = self._try_create(container)
        if errors or instance is None:
            raise Failure(ComponentCombinedError(errors=errors))

        return instance

    def _try_create(
        self,
        container: ComponentSystem | Engine | None,
    ) -> tuple[Component | None, list[ComponentError]]:
        from ceres.reference import unref

        parent = as_component_system(container)
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

        # Once the tree is built, walk every component and resolve cross-component
        # references, any references that cannot be resolved are reported as errors so
        # the caller can present them all at once.
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

        # Detach a partially constructed tree on error so we never leak components into
        # the parent system.
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
            # Reserved `__with_*` arguments inject the name, config, and container into
            # the component constructor without colliding with user arguments.
            instance = validate(
                self.cls,
                {
                    **self.arguments,
                    "__with_name__": self.name,
                    "__with_config__": self,
                    "__with_container__": container,
                },
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
                    exception=trace(exception),
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
        """Look up a nested component configuration by address.

        Args:
            address: Address relative to this configuration.

        Returns:
            The nested `ComponentConfig` at `address`, or `None` if any segment is
            missing.
        """
        current = self
        for name in address.names:
            if current is None:
                return None

            current = next((child for child in current.components if child.name == name), None)

        return current

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        """Look up the component class declared at `address`.

        Args:
            address: Address relative to this configuration.

        Returns:
            The `Component` subclass declared at `address`, or `None` if the address
            does not resolve.
        """
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


class ServiceConfig(DataObject):
    """Process-level options applied when running the engine as a system service."""

    name: Name | None = None
    """Service name registered with the operating system."""

    user: Name | None = None
    """User the service runs as."""

    stdout: Path | None = None
    """Optional path to redirect standard output to."""

    stderr: Path | None = None
    """Optional path to redirect standard error to."""


class ServerSSLConfig(DataObject):
    """TLS configuration for the engine's HTTP server."""

    key: Path | None = None
    """Path to the server private key file."""

    key_password: str | None = None
    """Password for an encrypted private key."""

    cert: Path | None = None
    """Path to the server certificate file."""

    version: int | None = ssl.PROTOCOL_TLS_SERVER
    """`ssl` protocol constant selecting the TLS version."""

    ca_certs: Path | None = None
    """Path to a CA bundle used when validating client certificates."""


class ServerAuthenticationConfig(DataObject):
    """Authentication settings for the engine's HTTP server."""

    secret: NonEmptyStr
    """Secret used to sign and verify authentication tokens."""

    duration: PositiveTimeDelta = timedelta(minutes=30)
    """Lifetime of an issued authentication token."""


class ServerCORSConfig(DataObject):
    """Cross-origin resource sharing settings for the engine's HTTP server."""

    enabled: bool = True
    allow_origins: MaybeSequence[str] = Field(default_factory=list)
    allow_origin_regex: Pattern[str] | None = None
    allow_methods: MaybeSequence[str] = "*"
    allow_headers: MaybeSequence[str] = "*"
    allow_credentials: bool = True
    expose_headers: MaybeSequence[str] = Field(default_factory=list)
    max_age: PositiveInt = 600


class ServerCompressionConfig(DataObject):
    """Response compression settings for the engine's HTTP server."""

    enabled: bool = True
    min_size: ByteSize = ByteSize(500)
    """Minimum response size in bytes before compression is applied."""

    zstd: bool = True
    zstd_level: int = Field(default=1, ge=1, le=22)
    brotli: bool = True
    brotli_quality: int = Field(default=4, ge=0, le=11)
    gzip: bool = True
    gzip_level: int = Field(default=1, ge=0, le=9)


class ServerConfig(DataObject):
    """Configuration for the engine's HTTP server."""

    host: str = "0.0.0.0"  # Bind to IPV4 all addresses by default.
    """Address the server binds to."""

    port: int | None = None
    """Port the server listens on, omit to disable the server."""

    ssl: ServerSSLConfig | None = None
    authentication: ServerAuthenticationConfig | None = None
    cors: ServerCORSConfig | None = None
    compression: ServerCompressionConfig | None = None

    @field_validator("host")
    def _validate_host(cls, host: str) -> str:
        validate(IPvAnyAddress, host)
        return host


class ConsoleConfig(DataObject):
    """Branding and layout options for the engine's web console."""

    title: str | None = None
    """Title shown in the console's browser tab and header."""

    favicon: Path | None = None
    """Path to a favicon image served by the console."""

    # `SerializeAsAny` works around a Pydantic union-serialization bug for `T | Sequence[T]`,
    # see https://github.com/pydantic/pydantic/milestone/13.
    dashboard: SerializeAsAny[MaybeSequence[Address] | None] = None
    """Address (or addresses) of components rendered as the console dashboard."""


class DatabaseRetryConfig(DataObject):
    """Retry policy used when connecting to the database."""

    timeout: PositiveTimeDelta = timedelta(seconds=15)
    """Total time to keep retrying before giving up."""

    interval: PositiveTimeDelta = timedelta(seconds=3)
    """Delay between retry attempts."""


class DatabaseConfigHooks(DataObject):
    """SQL statements executed at well-known points in the database lifecycle."""

    init: list[str] | None = None
    """Statements run once when the database is first created."""

    connect: list[str] | None = None
    """Statements run on every new connection."""

    close: list[str] | None = None
    """Statements run before a connection is closed."""


class HashType(StrEnum):
    """Hashing algorithm selector for password storage."""

    BCRYPT = "bcrypt"
    ARGON2 = "argon2"


class _HashingConfig(DataObject):
    type: HashType


class BCryptHashingConfig(_HashingConfig):
    """Configuration for the bcrypt password hashing algorithm."""

    type: Literal[HashType.BCRYPT] = HashType.BCRYPT
    rounds: int = Field(default=12, ge=4)
    """Cost factor controlling how expensive each hash is to compute."""


class Argon2HashingConfig(_HashingConfig):
    """Configuration for the Argon2id password hashing algorithm.

    Default parameters mirror `argon2.profiles.RFC_9106_LOW_MEMORY`, callers can tune
    them to trade memory and CPU cost against latency.
    """

    type: Literal[HashType.ARGON2] = HashType.ARGON2
    time_cost: PositiveInt = 3
    """Number of iterations Argon2 performs."""

    memory_cost: int = Field(default=65536, ge=8)  # Default is 64 MiB.
    """Memory budget in KiB."""

    parallelism: PositiveInt = 4
    """Number of parallel lanes used during hashing."""

    hash_length: int = Field(default=32, ge=4, le=256)  # True allowed range is 4-32768.
    """Length of the produced hash in bytes."""

    salt_length: int = Field(default=16, ge=8, le=64)  # True allowed range is 8-4096.
    """Length of the random salt in bytes."""

    @field_validator("parallelism")
    def _validate_memory_cost(cls, value: int, info: ValidationInfo) -> int:
        # Argon2 requires `memory_cost / parallelism >= 8`, enforce that here so a bad
        # combination is caught at config load time rather than at hash time.
        memory_cost = info.data.get("memory_cost", 65536)
        if (memory_cost / value) < 8:
            raise ValueError("parallelism must be at least 8 times smaller than memory_cost")

        return value


HashingConfig: TypeAlias = BCryptHashingConfig | Argon2HashingConfig
"""Discriminated union of hashing configurations, dispatched by the `type` field."""


class _DatabaseConfig(DataObject):
    type: DatabaseType
    hooks: DatabaseConfigHooks = Field(default_factory=DatabaseConfigHooks)
    engine: dict[str, Any] = Field(default_factory=dict)
    """Extra keyword arguments forwarded to the SQLAlchemy engine factory."""

    hashing: HashingConfig = Field(default_factory=Argon2HashingConfig, discriminator="type")
    """Password hashing configuration used for users stored in this database."""

    query: dict[str, MaybeSequence[str]] | None = None
    """Optional database-specific connection string query parameters."""


class SQLiteDatabaseConfig(_DatabaseConfig):
    """Configuration for a SQLite-backed database, the default for local deployments."""

    type: Literal[DatabaseType.SQLITE] = DatabaseType.SQLITE
    path: Path | None = None
    """Path to the SQLite file, omit to use an in-memory database."""


class PostgresDatabaseConfig(_DatabaseConfig):
    """Configuration for a PostgreSQL-backed database."""

    type: Literal[DatabaseType.POSTGRES] = DatabaseType.POSTGRES
    host: NonBlankStr
    port: NonNegativeInt | None = None
    database: NonBlankStr
    user: NonBlankStr
    password: SecretStr | None = None


DatabaseConfig: TypeAlias = SQLiteDatabaseConfig | PostgresDatabaseConfig
"""Discriminated union of database configurations, dispatched by the `type` field."""


class ConfigCheckType(StrEnum):
    """Identifies optional checks performed during `Config.load`."""

    DATABASE = "database"
    """Verify the database is reachable and accepts connections."""

    COMPONENTS = "components"
    """Verify the component tree builds without errors."""

    @classmethod
    def all(cls) -> tuple[ConfigCheckType, ...]:
        """Return every defined check, useful as the default for `Config.load`."""
        return tuple(cls)


class ConfigMeta(DataObject, config=ConfigDict(extra="allow")):
    """Engine-level configuration without the component tree.

    `ConfigMeta` covers the fixed parts of a Ceres configuration (service options,
    HTTP server, console, database, logging). It allows extra fields so that tooling
    can layer additional metadata without requiring schema changes here. The full
    `Config` type extends `ConfigMeta` with the component tree.
    """

    service: ServiceConfig = Field(default_factory=ServiceConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    database: DatabaseConfig = Field(default_factory=SQLiteDatabaseConfig, discriminator="type")
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def read(cls, source: ConfigSource[Self]) -> Self:
        """Read and validate a configuration from a path, mapping, or existing instance.

        Args:
            source: A path to a YAML file, an in-memory mapping, or an already-validated
                instance of this class.

        Returns:
            A validated configuration instance.

        Raises:
            Failure: Wraps a `ConfigReadError`, `ConfigParseError`,
                `ConfigInvalidSourceError`, or `ConfigValidationError` describing what
                went wrong while loading the configuration.
        """
        import yaml
        from yaml import MarkedYAMLError, YAMLError

        if isinstance(source, cls):
            return source

        if isinstance(source, Mapping):
            data = source
        elif isinstance(source, Path):
            try:
                path = source.resolve()
            except Exception:
                raise Failure(ConfigReadError(message=f"path '{source}' could not be resolved"))

            try:
                with open(path) as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                raise Failure(ConfigReadError(message=f"failed to read file at '{path}'"))
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

                raise Failure(ConfigParseError(message=message, location=location))
        else:
            raise Failure(ConfigInvalidSourceError(message=f"invalid source type: {type(source)}"))

        try:
            instance = validate(cls, data)
        except ValidationError as error:
            raise Failure(ConfigValidationError(problems=ValidationProblem.extract(error, data)))

        return instance

    @classmethod
    async def load(
        cls,
        config: ConfigSource[Self],
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
    ) -> Self:
        """Read a configuration and run optional sanity checks before returning it.

        Args:
            config: Source to load the configuration from, accepts the same forms as
                `read`.
            checks: Subset of checks to perform, defaults to running every defined check.

        Returns:
            The validated configuration.

        Raises:
            Failure: Wraps a `ConfigCombinedError` describing every check failure or
                read error encountered.
        """
        errors: list[ConfigError] = []
        config = cls.read(config)

        if ConfigCheckType.DATABASE in checks:
            errors.extend(await config._check_database())
        if ConfigCheckType.COMPONENTS in checks:
            errors.extend(await config._check_components())

        if errors:
            raise Failure(ConfigCombinedError(errors=errors))

        return config

    async def _check_database(self) -> list[DatabaseError]:
        from ceres.database import Database

        database = Database(self.database)
        try:
            async with database.connect():
                pass
        except Failure as failure:
            if isinstance(failure.error, DatabaseError):
                return [failure.error]

            return [DatabaseUnexpectedError(reason=failure.message)]
        except Exception as exception:
            return [DatabaseUnreachableError(reason=str(exception))]

        return []

    async def _check_components(self) -> list[ComponentError]:
        return []


class Config(ConfigMeta, config={"extra": "forbid"}):
    """Top-level Ceres configuration, including the component tree.

    `Config` is the strict, fully-typed view of a configuration file. Unknown fields
    are rejected here so users get clear errors for typos. The root of the component
    tree is always present, callers can also write `components:` at the top level as
    a shorthand and it will be folded into `root.components` automatically.
    """

    root: ComponentConfig = Field(default_factory=lambda: ComponentConfig(name="root"))
    """Root of the component tree, every other component nests under this one."""

    @model_validator(mode="before")
    @to_kwargs
    @classmethod
    def _validate_before(cls, values: object | Mapping[str, Any]) -> object:
        # Accept `components:` at the top level as shorthand for `root: { components: ... }`,
        # this lets simple configurations skip the explicit root wrapper.
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

        # Dashboard components must exist and must be `Interface` subclasses, this is
        # validated up front so dashboard misconfiguration fails at config load time.
        if self.console.dashboard is not None:
            for address in seq(self.console.dashboard):
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
        # The root component's name is fixed, default it when omitted so users do not
        # have to repeat it in every configuration file.
        if isinstance(values, Mapping):
            if "name" not in values:
                values = {"name": "root", **values}

        return values

    @override
    async def _check_components(self) -> list[ComponentError]:
        try:
            self.root.create()
            return []
        except Failure as failure:
            if isinstance(failure.error, ComponentCombinedError):
                return failure.error.errors
            elif isinstance(failure.error, ComponentError):
                return [failure.error]
            else:
                return [ComponentUnexpectedError(exception=trace(failure))]
        except Exception as exception:
            return [ComponentUnexpectedError(exception=trace(exception))]

    def get_component(self, address: DynamicAddress) -> ComponentConfig | None:
        """Look up a component configuration anywhere under the root."""
        return self.root.get_component(address)

    def get_components(
        self,
        address: AddressSelector | None = None,
    ) -> dict[Address, ComponentConfig]:
        """Return every component configuration in the tree, optionally filtered.

        Args:
            address: Optional selector restricting which addresses are returned, omit
                to return every component including the root.

        Returns:
            Mapping from absolute address to component configuration.
        """
        configs: dict[Address, ComponentConfig] = {}

        def recurse(config: ComponentConfig, address: Address, selector: AddressSelector | None):
            if not selector or selector.matches(address, Address.ROOT):
                configs[address] = config

            for child in config.components:
                recurse(child, address / child.name, selector)

        recurse(self.root, Address.ROOT, address)

        return configs

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        """Look up the component class declared at `address`, anywhere under the root."""
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


type ConfigSource[T: DataObject] = Path | Mapping[str, object] | T
"""Anything that can be turned into a configuration of type `T` via `ConfigMeta.read`."""
