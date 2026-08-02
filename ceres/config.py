from abc import abstractmethod
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self, TypeAlias, override

from pydantic import (
    ByteSize,
    ConfigDict,
    Discriminator,
    Field,
    ImportString,
    NonNegativeInt,
    SecretStr,
    Tag,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from ceres.__internal__.core import Argon2HashingConfig as _CoreArgon2HashingConfig
from ceres.__internal__.core import BCryptHashingConfig as _CoreBCryptHashingConfig
from ceres.__internal__.core import ConsoleConfig as _CoreConsoleConfig
from ceres.__internal__.core import DatabaseConfigHooks as _CoreDatabaseConfigHooks
from ceres.__internal__.core import LoggingConfig as _CoreLoggingConfig
from ceres.__internal__.core import PostgresDatabaseConfig as _CorePostgresDatabaseConfig
from ceres.__internal__.core import ServerAuthenticationConfig as _CoreServerAuthenticationConfig
from ceres.__internal__.core import ServerCompressionConfig as _CoreServerCompressionConfig
from ceres.__internal__.core import ServerConfig as _CoreServerConfig
from ceres.__internal__.core import ServerCORSConfig as _CoreServerCORSConfig
from ceres.__internal__.core import ServerSSLConfig as _CoreServerSSLConfig
from ceres.__internal__.core import ServiceConfig as _CoreServiceConfig
from ceres.__internal__.core import SQLiteDatabaseConfig as _CoreSQLiteDatabaseConfig
from ceres.__internal__.core import TursoDatabaseConfig as _CoreTursoDatabaseConfig
from ceres.__internal__.interop import RustConfigModel
from ceres.__internal__.utilities.collections import group_by, seq, uniq
from ceres.__internal__.utilities.typing import as_component_system, as_engine
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.alert import AlertFilter
from ceres.constants import DEFAULT_BUFFER_DROP, DEFAULT_BUFFER_SIZE
from ceres.data import (
    DataObject,
    Name,
    OrderedStrEnum,
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
    Error,
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
    from ceres.reference import Reference
    from ceres.sieve import FunctionSieve, Sieve
else:
    Sieve = Any
    Component = Any
    Connection = Any
    ConnectionField = Any

__all__ = [
    "Config",
]


def _level_or_bool(value: bool | str) -> bool | Level:
    """Convert a native toggle value into its Python form."""
    if isinstance(value, bool):
        return value

    return Level(value)


class LoggingConfig(RustConfigModel, _CoreLoggingConfig):
    """Per-component or per-engine logging configuration.

    The fields and their validation live in the native `ceres.__internal__.core.LoggingConfig`, this
    subclass wires the class into Pydantic and converts level values into `Level`. Each field
    controls a different sink, `output` and `store` set minimum levels for the streamed and
    persisted log streams, the boolean-or-level fields enable optional logging of specific
    record types and accept either a level (enable at that level) or a boolean (enable at the
    default level when `True`, disable when `False`).
    """

    if TYPE_CHECKING:

        @property
        @override
        def output(self) -> Level: ...

        @property
        @override
        def store(self) -> Level: ...

        @property
        @override
        def events(self) -> bool | Level: ...

        @property
        @override
        def messages(self) -> bool | Level: ...

        @property
        @override
        def particles(self) -> bool | Level: ...

        @property
        @override
        def alerts(self) -> bool | Level: ...

    __field_wrappers__ = {
        "output": Level,
        "store": Level,
        "events": _level_or_bool,
        "messages": _level_or_bool,
        "particles": _level_or_bool,
        "alerts": _level_or_bool,
    }

    @override
    def merged(self, other: _CoreLoggingConfig) -> Self:
        """Overlay another configuration's explicitly-set fields onto this one."""
        combined = _CoreLoggingConfig.merged(self, other)
        return type(self)(**combined.provided())


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


def collect_unresolved_reference_errors(
    components: Iterable[Component],
    skip: Callable[[Reference], bool] | None = None,
) -> list[ComponentError]:
    """Re-resolve every component's references and report those that still do not resolve.

    Run this after every top-level tree exists so absolute cross-tree references can route
    through the engine. Intra-tree references have already been resolved during creation.

    Args:
        components: The components whose references to re-synchronize.
        skip: Optional predicate that returns `True` for a reference whose non-resolution should
            not be reported, used to defer cross-tree references until every tree exists.

    Returns:
        A `ComponentReferenceInvalidError` for each reference that remains unresolved.
    """
    from ceres.reference import unref

    errors: list[ComponentError] = []
    for component in components:
        _, unresolved = component.system.sync_references()
        for reference in unresolved:
            if skip is not None and skip(reference):
                continue

            errors.append(
                ComponentReferenceInvalidError(
                    address=component.system.address,
                    referenced=reference.__reference_ultimate_target__,
                    expected=reference.__reference_constraint__ or Component,
                    actual=type(unref(reference)),
                )
            )

    return errors


class ComponentAccessLevel(OrderedStrEnum):
    """Access level controlling what a user may do with a component.

    The hierarchy is strict: each level implies all levels below it. `DENY` is only valid
    as a default access level on a component definition and means no access unless
    explicitly granted.

    Defined here rather than in `ceres.component` because `ComponentConfig` needs it as a
    field type and `ceres.component` already imports from this module at load time.
    `ceres.component` re-exports this enum for API discoverability.
    """

    DENY = "deny"
    """No access, the component is invisible to the user."""
    VIEW = "view"
    """Can see the component and view its data."""
    OPERATE = "operate"
    """Can invoke actions and send data on connections."""
    MANAGE = "manage"
    """Can change configuration and manage permissions."""


RawComponentAccessLevel = Literal["deny", "view", "operate", "manage"]
ComponentAccessLevelInput = ComponentAccessLevel | RawComponentAccessLevel


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

    tags: list[str] = Field(default_factory=list)
    """Arbitrary labels for cross-cutting permission grants."""

    access: ComponentAccessLevel | None = None
    """Default access level for this component, inherited by children when not overridden."""

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
                the new component to. Pass `None` to construct a detached top-level
                component.

        Returns:
            The instantiated component, fully wired with children and references resolved.

        Raises:
            ComponentCombinedError: If any errors are encountered while constructing the
                component tree.
        """
        container = as_component_system(container) or as_engine(container)
        instance, errors = self._try_create(container)
        if errors or instance is None:
            raise ComponentCombinedError(errors=errors)

        return instance

    def _try_create(
        self,
        container: ComponentSystem | Engine | None,
    ) -> tuple[Component | None, list[ComponentError]]:
        parent = as_component_system(container)
        if parent is not None:
            address = parent.address / self.name
        else:
            address = Address(f"@{self.name}")

        # Top-level trees under an engine are created one at a time, so an absolute
        # reference into a sibling tree cannot resolve until every tree exists. Defer those
        # out of the per-tree check and let the engine validate them across all trees.
        defer_absolute = as_engine(container) is not None

        def skip(reference: Reference) -> bool:
            target = reference.__reference_ultimate_target__
            return defer_absolute and isinstance(target, DynamicAddress) and target.is_absolute

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
            errors.extend(
                collect_unresolved_reference_errors(
                    instance.system.get_components(inclusive=True),
                    skip=skip,
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


class ServiceConfig(RustConfigModel, _CoreServiceConfig):
    """Process-level options applied when running the engine as a system service.

    The fields and their validation live in the native `ceres.__internal__.core.ServiceConfig`, this
    subclass only wires the class into Pydantic.
    """


class ServerSSLConfig(RustConfigModel, _CoreServerSSLConfig):
    """TLS configuration for the engine's HTTP server.

    The fields and their validation live in the native
    `ceres.__internal__.core.ServerSSLConfig`, this subclass only wires the class into
    Pydantic.
    """


class ServerAuthenticationConfig(RustConfigModel, _CoreServerAuthenticationConfig):
    """Authentication settings for the engine's HTTP server.

    The fields and their validation live in the native
    `ceres.__internal__.core.ServerAuthenticationConfig`,
    this subclass only wires the class into Pydantic. The `secret` is never served over the
    API, the config routes drop it, along with every other credential in the configuration,
    through `scrub_credentials`.
    """


class ServerCORSConfig(RustConfigModel, _CoreServerCORSConfig):
    """Cross-origin resource sharing settings for the engine's HTTP server.

    The fields and their validation live in the native
    `ceres.__internal__.core.ServerCORSConfig`, this subclass only wires the class into
    Pydantic.
    """


class ServerCompressionConfig(RustConfigModel, _CoreServerCompressionConfig):
    """Response compression settings for the engine's HTTP server.

    The fields and their validation live in the native
    `ceres.__internal__.core.ServerCompressionConfig`, this subclass only wires the class
    into Pydantic.
    """


class ServerConfig(RustConfigModel, _CoreServerConfig):
    """Configuration for the engine's HTTP server.

    The fields and their validation live in the native `ceres.__internal__.core.ServerConfig`, this
    subclass only wires the class into Pydantic.
    """


class ConsoleConfig(RustConfigModel, _CoreConsoleConfig):
    """Branding and layout options for the engine's web console.

    The fields and their validation live in the native `ceres.__internal__.core.ConsoleConfig`, this
    subclass only wires the class into Pydantic.
    """


class DatabaseConfigHooks(RustConfigModel, _CoreDatabaseConfigHooks):
    """SQL statements executed at well-known points in the database lifecycle.

    The fields and their validation live in the native
    `ceres.__internal__.core.DatabaseConfigHooks`, this subclass only wires the class into
    Pydantic.
    """


class HashType(StrEnum):
    """Hashing algorithm selector for password storage."""

    BCRYPT = "bcrypt"
    ARGON2 = "argon2"


class BCryptHashingConfig(RustConfigModel, _CoreBCryptHashingConfig):
    """Configuration for the bcrypt password hashing algorithm.

    The fields and their validation live in the native
    `ceres.__internal__.core.BCryptHashingConfig`, this subclass wires the class into
    Pydantic and converts the selector into `HashType`.
    """

    if TYPE_CHECKING:

        @property
        @override
        def type(self) -> Literal[HashType.BCRYPT]: ...

    __type_tag__ = "bcrypt"
    __field_wrappers__ = {"type": HashType}


class Argon2HashingConfig(RustConfigModel, _CoreArgon2HashingConfig):
    """Configuration for the Argon2id password hashing algorithm.

    Default parameters mirror `argon2.profiles.RFC_9106_LOW_MEMORY`, callers can tune
    them to trade memory and CPU cost against latency. The fields and their validation
    live in the native `ceres.__internal__.core.Argon2HashingConfig`.
    """

    if TYPE_CHECKING:

        @property
        @override
        def type(self) -> Literal[HashType.ARGON2]: ...

    __type_tag__ = "argon2"
    __field_wrappers__ = {"type": HashType}


HashingConfig: TypeAlias = BCryptHashingConfig | Argon2HashingConfig
"""Union of hashing configurations, dispatched by the `type` field."""


class SQLiteDatabaseConfig(RustConfigModel, _CoreSQLiteDatabaseConfig):
    """Configuration for a SQLite-backed database, the default for local deployments.

    The fields and their validation live in the native
    `ceres.__internal__.core.SQLiteDatabaseConfig`, this subclass wires the class into
    Pydantic and converts the selector into `DatabaseType`.
    """

    if TYPE_CHECKING:

        @property
        @override
        def type(self) -> Literal[DatabaseType.SQLITE]: ...

    __type_tag__ = "sqlite"
    __field_wrappers__ = {"type": DatabaseType}


class TursoDatabaseConfig(SQLiteDatabaseConfig, _CoreTursoDatabaseConfig):
    """Configuration for a Turso-backed database, a SQLite-compatible file that allows
    concurrent writers.

    Turso reads and writes the same file format as SQLite and takes the same path settings, so this
    inherits them. What it adds is MVCC journaling, which lets several connections write at once
    instead of serializing behind one writer.

    Left at its defaults this is a drop-in replacement for `SQLiteDatabaseConfig`. It writes an
    ordinary SQLite file either engine can open, and the suite passes against it exactly as it does
    against SQLite. `mvcc` is the one setting that changes that, in what it allows and in what it
    irreversibly does to the file.

    **Turning `mvcc` on converts the database file and the conversion cannot be undone.** MVCC
    rewrites the file into a format SQLite does not recognize, after which `sqlite3` reports "file
    is not a database" and every other SQLite tool fails the same way. Back the file up first and
    treat turning it on as a migration rather than as a setting. It is also off by default because
    overlapping writers are optimistic rather than blocking. Two transactions touching the same
    rows both proceed and the second fails when it commits, so a caller has to be prepared to
    retry.

    What takes the setting up on is the record writer. A flush of buffered records opens a
    transaction that may overlap other writers, and one that loses a race is put back and written
    with the next flush. Every other write, and every migration, takes the write lock as it always
    did, because those are neither frequent nor safe to run twice.

    Turso is compiled into Ceres, so this backend needs nothing installed alongside it.
    """

    if TYPE_CHECKING:

        @property
        @override
        def type(self) -> Literal[DatabaseType.TURSO]: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    __type_tag__ = "turso"


def _secret_or_none(value: str | None) -> SecretStr | None:
    """Wrap a native secret value into `SecretStr`."""
    if value is None:
        return None

    return SecretStr(value)


class PostgresDatabaseConfig(RustConfigModel, _CorePostgresDatabaseConfig):
    """Configuration for a PostgreSQL-backed database.

    The fields and their validation live in the native
    `ceres.__internal__.core.PostgresDatabaseConfig`, this subclass wires the class into
    Pydantic, converts the selector into `DatabaseType`, and wraps the password into
    `SecretStr`.
    """

    if TYPE_CHECKING:

        @property
        @override
        def type(self) -> Literal[DatabaseType.POSTGRES]: ...

        @property
        @override
        def password(self) -> SecretStr | None: ...  # pyright: ignore[reportIncompatibleMethodOverride]

    __type_tag__ = "postgres"
    __field_wrappers__ = {"type": DatabaseType, "password": _secret_or_none}


def _database_config_type(value: Any) -> Any:
    """Read the database union selector from a mapping or an instance."""
    if isinstance(value, Mapping):
        return value.get("type")

    return getattr(value, "type", None)


DatabaseConfig: TypeAlias = SQLiteDatabaseConfig | TursoDatabaseConfig | PostgresDatabaseConfig
"""Union of database configurations, dispatched by the `type` field."""


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
    database: Annotated[
        Annotated[SQLiteDatabaseConfig, Tag("sqlite")]
        | Annotated[TursoDatabaseConfig, Tag("turso")]
        | Annotated[PostgresDatabaseConfig, Tag("postgres")],
        Discriminator(_database_config_type),
    ] = Field(default_factory=SQLiteDatabaseConfig)
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
            ConfigReadError: If the source path cannot be resolved or the file cannot be
                read.
            ConfigParseError: If the YAML content cannot be parsed.
            ConfigInvalidSourceError: If the source type is not supported.
            ConfigValidationError: If the parsed data fails schema validation.
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
                raise ConfigReadError(message=f"path '{source}' could not be resolved")

            try:
                with open(path) as stream:
                    data = yaml.safe_load(stream)
            except OSError:
                raise ConfigReadError(message=f"failed to read file at '{path}'")
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

                raise ConfigParseError(message=message, location=location)
        else:
            raise ConfigInvalidSourceError(message=f"invalid source type: {type(source)}")

        try:
            instance = validate(cls, data)
        except ValidationError as error:
            raise ConfigValidationError(problems=ValidationProblem.extract(error, data))

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
            ConfigCombinedError: If any check failures or read errors are encountered.
        """
        errors: list[ConfigError] = []
        config = cls.read(config)

        if ConfigCheckType.DATABASE in checks:
            errors.extend(await config._check_database())
        if ConfigCheckType.COMPONENTS in checks:
            errors.extend(await config._check_components())

        if errors:
            raise ConfigCombinedError(errors=errors)

        return config

    async def _check_database(self) -> list[DatabaseError]:
        from ceres.database import Database

        database = Database(self.database)
        try:
            await database._store().fetch("SELECT 1", [])
        except Error as error:
            if isinstance(error, DatabaseError):
                return [error]

            return [DatabaseUnexpectedError(reason=error.type)]
        except Exception as exception:
            return [DatabaseUnreachableError(reason=str(exception))]

        return []

    async def _check_components(self) -> list[ComponentError]:
        return []


class Config(ConfigMeta, config={"extra": "forbid"}):
    """Top-level Ceres configuration, including the component tree.

    `Config` is the strict, fully-typed view of a configuration file. Unknown fields
    are rejected here so users get clear errors for typos. `components` holds every
    top-level component configuration, there is no implicit wrapping root component.
    """

    components: list[ComponentConfig] = Field(default_factory=list)
    """Top-level component configurations, the engine's components."""

    tags: list[str] = Field(default_factory=list)
    """Tags inherited by every component that does not override them."""

    access: ComponentAccessLevel | None = None
    """Default access level for components with none declared in their ancestor chain."""

    @field_validator("components")
    def _validate_components(cls, components: list[ComponentConfig]) -> list[ComponentConfig]:
        for component_name, group in group_by(components, lambda current: current.name):
            if len(list(group)) > 1:
                raise ValueError(f"duplicate top-level component name '{component_name}'")

        return components

    @override
    async def _check_components(self) -> list[ComponentError]:
        from ceres.engine import Engine

        errors: list[ComponentError] = []

        # Create every top-level tree under a shared throwaway engine so absolute
        # cross-tree references resolve during checks exactly as they do at load time.
        engine = Engine()
        # Building a component registers its connections, sieves, and jobs, and each
        # registration emits an event. A check is a question, not a run, so those events
        # describe a tree that is discarded a few lines below and nothing happened worth
        # telling anyone about. The engine's own logging configuration is what the tree
        # inherits, so turning the record toggles off there silences the whole check.
        engine._config = Config(
            logging=LoggingConfig(events=False, messages=False, particles=False, alerts=False)
        )
        try:
            for config in self.components:
                try:
                    config.create(engine)
                except Error as error:
                    if isinstance(error, ComponentCombinedError):
                        errors.extend(error.errors)
                    elif isinstance(error, ComponentError):
                        errors.append(error)
                    else:
                        errors.append(ComponentUnexpectedError(exception=trace(error)))
                except Exception as exception:
                    errors.append(ComponentUnexpectedError(exception=trace(exception)))

            # Cross-tree references were deferred during per-tree creation, validate them
            # now that every tree exists.
            errors.extend(collect_unresolved_reference_errors(engine.get_components()))
        finally:
            await engine.database.dispose()

        return errors

    def get_component(self, address: DynamicAddress) -> ComponentConfig | None:
        """Look up a component configuration anywhere in the tree."""
        names = address.names
        if not names:
            return None

        current = next((child for child in self.components if child.name == names[0]), None)
        if current is None:
            return None

        return current.get_component(DynamicAddress(".".join(names[1:]))) if names[1:] else current

    def get_components(
        self,
        address: AddressSelector | None = None,
    ) -> dict[Address, ComponentConfig]:
        """Return every component configuration in the tree, optionally filtered.

        Args:
            address: Optional selector restricting which addresses are returned, omit
                to return every component in the tree.

        Returns:
            Mapping from absolute address to component configuration.
        """
        configs: dict[Address, ComponentConfig] = {}

        def recurse(config: ComponentConfig, address: Address, selector: AddressSelector | None):
            if not selector or selector.matches(address, None):
                configs[address] = config

            for child in config.components:
                recurse(child, address / child.name, selector)

        for config in self.components:
            recurse(config, Address(f"@{config.name}"), address)

        return configs

    def get_component_class(self, address: DynamicAddress) -> type[Component] | None:
        """Look up the component class declared at `address`, anywhere in the tree."""
        config = self.get_component(address)
        if config is None:
            return None

        return config.cls


type ConfigSource[T: DataObject] = Path | Mapping[str, object] | T
"""Anything that can be turned into a configuration of type `T` via `ConfigMeta.read`."""
