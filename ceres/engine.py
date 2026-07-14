import asyncio
import traceback
from collections.abc import Sequence
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, Unpack, final, override

import anyio
from pydantic import Field

from ceres.__internal__.lazy import __lazy_imports__
from ceres.__internal__.project import LoadedProject
from ceres.__internal__.server import Server
from ceres.__internal__.utilities.collections import uniq
from ceres.__internal__.utilities.typing import as_component_system
from ceres.address import Address, AddressSelector, DynamicAddress
from ceres.concurrency import sleep
from ceres.config import Config, ConfigCheckType, ConfigSource
from ceres.data import DataObject, Name, PasswordHash, dump, to_json
from ceres.directory import Directory
from ceres.error import (
    ComponentCombinedError,
    ComponentError,
    ComponentUnexpectedError,
    ConfigError,
    Error,
    ReloadConfigInvalidError,
    trace,
)
from ceres.event import AttachedEvent, StoppedEvent, StoppingEvent
from ceres.node import Node

if TYPE_CHECKING:
    from ceres.__internal__.entity import BaseEntityManager
    from ceres.component import Component, ComponentFilter, ComponentFilterArgs, ComponentSystem
    from ceres.entity import Entity

with __lazy_imports__(__name__):
    from ceres.database import Database
    from ceres.setting import SettingManager
    from ceres.user import UserManager
    from ceres.workspace import WorkspaceEditManager, WorkspaceManager, WorkspaceMembershipManager

__all__ = [
    "Engine",
]

SyncActionType = Literal[
    "load-pending-database-config",
    "load-pending-server-config",
    "create-component",
    "recreate-component",
    "remove-component",
]
"""Tag identifying the kind of work an `EngineAction` represents."""


class _EngineAction(DataObject):
    """Base type for actions the engine schedules when applying a new configuration."""

    type: SyncActionType


class LoadPendingDatabaseConfigEngineAction(_EngineAction):
    """Replace the engine's database with one built from the pending configuration."""

    type: Literal["load-pending-database-config"] = "load-pending-database-config"


class LoadPendingServerConfigEngineAction(_EngineAction):
    """Restart the HTTP server using the pending configuration."""

    type: Literal["load-pending-server-config"] = "load-pending-server-config"


class CreateComponentEngineAction(_EngineAction):
    """Create a brand new component at `address` from the pending configuration."""

    type: Literal["create-component"] = "create-component"
    address: Address


class RecreateComponentEngineAction(_EngineAction):
    """Stop and rebuild the component at `address`, replacing it with a fresh instance."""

    type: Literal["recreate-component"] = "recreate-component"
    address: Address


class RemoveComponentEngineAction(_EngineAction):
    """Stop and detach the component at `address` because the new configuration omits it."""

    type: Literal["remove-component"] = "remove-component"
    address: Address


EngineDatabaseAction = LoadPendingDatabaseConfigEngineAction
EngineServerAction = LoadPendingServerConfigEngineAction
EngineComponentAction = (
    CreateComponentEngineAction | RecreateComponentEngineAction | RemoveComponentEngineAction
)
EngineAction = EngineDatabaseAction | EngineServerAction | EngineComponentAction


class EngineActions(DataObject):
    """Plan describing how the engine should mutate its state to reach the pending configuration.

    The fields are populated by `Engine._get_apply_actions` and consumed by `Engine._apply`.
    """

    database: EngineDatabaseAction | None
    """Database reload action, or `None` if the database configuration is unchanged."""

    server: EngineServerAction | None
    """Server reload action, or `None` if the server configuration is unchanged."""

    components: Sequence[EngineComponentAction] = Field(default_factory=list)
    """Per-component actions in the order they must be executed to reach the new tree shape."""


@final
class Engine(Node):
    """Top-level container that owns the component forest and the supporting infrastructure.

    The engine is the entry point for a Ceres process. It owns the `Database`, the optional HTTP
    `Server`, and the forest of top-level components. It loads configuration, reconciles the
    running component forest with the desired configuration, and drives the lifecycle
    (start/stop) of everything beneath it.

    There is exactly one engine per Ceres process. Components reach it through
    `ComponentSystem.engine`.
    """

    __slots__ = (
        "_loaded",
        "_config",
        "_config_path",
        "_apply_lock",
        "_database",
        "_components",
        "_server",
    )

    def __init__(self) -> None:
        super().__init__()

        self._loaded = False
        self._config = Config()
        self._config_path: Path | None = None
        # Serializes concurrent `_apply` invocations so configuration reloads can't interleave.
        self._apply_lock = asyncio.Lock()
        self._database = Database()
        self._components: dict[Name, ComponentSystem] = {}
        self._server: Server | None = None

    @property
    @override
    def __container__(self) -> None:
        return None

    @property
    @override
    def address(self) -> Address:
        """The synthetic address used for the engine itself, always `Address.engine()`."""
        return Address.engine()

    @property
    @override
    def engine(self) -> Self:
        """Return this engine instance, satisfying the `Node.engine` interface."""
        return self

    @property
    def server(self) -> Server | None:
        """The currently running HTTP server, or `None` if no server is active."""
        return self._server

    @property
    @override
    def database(self) -> Database:
        """Return the engine's database instance."""
        return self._database

    @property
    @override
    def config(self) -> Config:
        """The configuration most recently applied to the engine."""
        return self._config

    @cached_property
    def users(self) -> UserManager:
        """Manager for user accounts."""
        return UserManager(self)

    @cached_property
    def settings(self) -> SettingManager:
        """Manager for engine-wide settings."""
        return SettingManager(self)

    @cached_property
    def workspaces(self) -> WorkspaceManager:
        """Manager for workspaces."""
        return WorkspaceManager(self)

    @cached_property
    def workspace_memberships(self) -> WorkspaceMembershipManager:
        """Manager for workspace memberships, mapping users into workspaces."""
        return WorkspaceMembershipManager(self)

    @cached_property
    def workspace_edits(self) -> WorkspaceEditManager:
        """Manager for in-progress workspace edits."""
        return WorkspaceEditManager(self)

    def __manager__(self, Entity: type[Entity], /) -> BaseEntityManager:
        """Return the entity manager bound to this engine for the given `Entity` type."""
        from ceres.__internal__.entity import get_entity_manager

        return get_entity_manager(self, Entity)

    @property
    def config_path(self) -> Path | None:
        """Filesystem path the current configuration was loaded from, if any."""
        return self._config_path

    @property
    def project_directory(self) -> Directory | None:
        """Directory containing the configuration file, or `None` if no path is known."""
        if self.config_path is None:
            return None

        return Directory(self.config_path.parent)

    @property
    def local_directory(self) -> Directory | None:
        """`local/` subdirectory beside the configuration file, used for persistent local state."""
        if self.project_directory is None:
            return None

        return self.project_directory.subdir("local")

    @override
    async def __run__(self) -> None:
        if self.local_directory is not None:
            self.local_directory.create()

        await self._apply(self.config_path, self.config)

        await self.__node_sync__()

        # Hydrate every component's persisted state in a single connection, then start each
        # top-level component that is enabled.
        async with await self.database.use() as connection:
            components = self.get_components()
            for component in components:
                await component.system.__node_sync__(connection)

            for system in list(self._components.values()):
                if system.enabled:
                    system.start(all_enabled=True)

        try:
            await super().__run__()
        finally:
            if self.stopping:
                self.log.info("Exit signal received, stopping.")

    @override
    def __stopping__(self) -> None:
        self.events.emit(StoppingEvent)

    @override
    async def __stop__(self) -> None:
        await self._stop_server()
        for system in list(self._components.values()):
            await system.stop()

    @override
    async def __post_stop__(self) -> None:
        await super().__post_stop__()
        self.events.emit(StoppedEvent)
        await self.flush()
        await self._database.dispose()

        self.log.info("Stopped.")

    @override
    def get_component(self, address: str | DynamicAddress | None = None) -> Component | None:
        """Look up a component by address anywhere in the forest.

        Args:
            address: An address string or `DynamicAddress`. `None` or an empty value
                returns `None`, there is no default component.

        Returns:
            The matching component, or `None` if nothing matches.
        """
        if address is None or not str(address):
            return None

        names = DynamicAddress(address).names
        if not names:
            return None

        top = self._components.get(names[0])
        if top is None:
            return None

        if len(names) == 1:
            return top.component

        return top.get_component(".".join(names[1:]))

    @override
    def get_components(
        self,
        filter: ComponentFilter | AddressSelector | None = None,
        /,
        *,
        inclusive: bool = False,
        **kwargs: Unpack[ComponentFilterArgs],
    ) -> list[Component]:
        """Walk every tree in the forest and return components matching the given filter.

        Args:
            filter: A `ComponentFilter` or `AddressSelector` to apply, or `None` to skip
                positional filtering.
            inclusive: Accepted for interface compatibility with `ComponentSystem.get_components`,
                the engine always includes every top-level component regardless.
            **kwargs: Additional filter overrides forwarded as `ComponentFilterArgs`.

        Returns:
            A list of matching components, or an empty list when the forest is empty.
        """
        components: list[Component] = []
        for system in self._components.values():
            components.extend(system.get_components(filter, inclusive=True, **kwargs))

        return components

    def attach(
        self,
        component: Component | ComponentSystem,
        /,
        name: Name | None = None,
    ) -> Component | None:
        """Attach a component as a top-level component of the engine's forest.

        Args:
            component: The component or component system to attach.
            name: Optional name to assign to the component before attaching it.

        Returns:
            The previously attached top-level component with the same name if one was
            replaced, otherwise `None`.
        """
        system = as_component_system(component)
        assert system is not None

        if name is not None:
            system.name = name

        previous = self._components.get(system.name)
        if previous is system:
            return None

        if previous is not None:
            previous.detach()

        system.detach()
        self._components[system.name] = system
        if system.container is not self:
            system.container = self
            system.events.emit(AttachedEvent)

        return previous.component if previous is not None else None

    def detach(self, component: Component | ComponentSystem, /) -> None:
        """Remove a top-level component from the engine's forest."""
        system = as_component_system(component)
        assert system is not None

        # Match by identity rather than name so a component renamed while attached still has
        # its old registration removed.
        for name, current in list(self._components.items()):
            if current is system:
                del self._components[name]

    async def load(
        self,
        source: ConfigSource[Config],
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        silent: bool = False,
    ) -> Config:
        """Load and apply a configuration from the given source.

        Args:
            source: Path to a configuration file, or a `Config` instance, or any other
                `ConfigSource[Config]`.
            checks: Configuration checks to run during loading.
            silent: When `True`, suppress informational logging.

        Returns:
            The fully resolved `Config` that was applied.
        """
        config = await Config.load(source, checks=checks)

        if not silent:
            if isinstance(source, Path):
                self.log.info(f"Loading configuration from '{source}'.")
            else:
                self.log.info("Loading provided configuration.")

        await self._apply(source if isinstance(source, Path) else None, config, silent=silent)
        return config

    async def reload(
        self,
        *,
        checks: Sequence[ConfigCheckType] = ConfigCheckType.all(),
        silent: bool = False,
    ) -> Config:
        """Re-load the current configuration from disk, falling back to the in-memory copy.

        Args:
            checks: Configuration checks to run during loading.
            silent: When `True`, suppress informational logging.

        Returns:
            The freshly loaded `Config` that was applied.

        Raises:
            ReloadConfigInvalidError: If the configuration file fails validation. Wrap
                the underlying `ConfigError` so callers can distinguish reload-time
                validation problems from other errors.
        """
        if self.config_path is not None:
            self.log.info(f"Reloading configuration from '{self.config_path}'.")
            source = self.config_path
        else:
            self.log.info("Reloading current configuration.")
            source = self.config

        try:
            config = await Config.load(source, checks=checks)
        except Error as error:
            if not isinstance(error, ConfigError):
                raise

            raise ReloadConfigInvalidError(error=error)

        await self._apply(source if isinstance(source, Path) else None, config, silent=silent)
        return config

    async def hash_password(self, password: str) -> PasswordHash:
        """Hash a plaintext password using the engine's database password hasher."""
        return await self._database.hash_password(password)

    async def verify_password(self, password: str, hash: PasswordHash) -> bool:
        """Verify a plaintext password against a previously stored hash."""
        return await self._database.verify_password(password, hash)

    async def _prepare_database(self) -> None:
        """Bring the database schema current before components are created or servers start.

        An empty database has all migrations applied, an existing one must already be current.

        Raises:
            DatabaseVersionError: If the database has pending or unknown migrations.
        """
        if not await self.database.initialized():
            self.log.info("Database appears empty, running migrations.")
            try:
                await self.database.migrate()
                self.log.info("Database migrated successfully.")
            except Error:
                self.log.error("Database migration failed.")
                raise
        else:
            await self.database.assert_schema_current()

    def _create_server(self) -> Server | None:
        if self.config_path is None:
            self.log.error("Cannot create server without configuration path.")
            return None

        return Server(self, LoadedProject(self.config_path, self.config), self.config.server)

    async def _start_server(self) -> Server | None:
        if self._server is None:
            self._server = self._create_server()

        if self._server is not None and not self._server.running:
            self.log.info("Starting HTTP server.")
            self._server.start(on_exception=self._on_server_exception)

            # Give the server a moment to bind so the bind address can be logged. If it isn't
            # ready within a second we move on, the server will eventually log on its own.
            with anyio.move_on_after(1):
                while self._server.cli_bind is None:
                    await sleep(0.01)

            if self._server.cli_bind:
                self.log.info(f"HTTP CLI server listening on {self._server.cli_bind}.")
            if self._server.bind:
                self.log.info(f"HTTP web server listening on {self._server.bind}.")

        return self._server

    async def _stop_server(self) -> None:
        if self._server is not None:
            self.log.info("Stopping HTTP server.")
            await self._server.stop()
            self._server = None
            self.log.info("HTTP server stopped.")

    def _on_server_exception(self, server: Server, exception: BaseException) -> None:
        self.log.error(f"An exception occurred while running server: {exception}")

    async def _apply(
        self,
        config_path: Path | None,
        config: Config,
        *,
        silent: bool = False,
    ) -> EngineActions:
        # Hold the apply lock so two configuration loads can't race and leave the tree in an
        # inconsistent state.
        async with self._apply_lock:
            self._config_path = config_path
            self._config = config

            # Snapshot which components are currently running, we'll restart them at the end.
            running = [component.system.address for component in self.get_components(running=True)]

            reloading = self._loaded

            verb = "reload" if reloading else "load"

            actions = self._get_apply_actions(config)
            if actions.server is None and actions.database is None and not actions.components:
                if not reloading:
                    # A first load whose configuration matches the current state still needs
                    # the database brought current before anything runs against it.
                    await self._prepare_database()

                if not silent:
                    self.log.info("Configuration appears up-to-date.")

                self._loaded = True
                return actions

            if not silent:
                self.log.debug("Actions pending: " + to_json(actions))

            if actions.database is not None:
                if not silent:
                    self.log.info(f"Database configuration will be {verb}ed.")
                try:
                    for system in list(self._components.values()):
                        await system.stop()

                    await self._database.dispose()
                    self._database = Database(config.database)
                    if not silent:
                        self.log.info(f"Database configuration {verb}ed successfully.")
                except Exception:
                    self.log.error(
                        f"An issue occurred while reloading the database: {traceback.format_exc()}"
                    )

            # Bring the database current before creating components or starting the server, so
            # a version mismatch aborts the load before anything binds or constructs.
            if not reloading or actions.database is not None:
                await self._prepare_database()

            if actions.components:
                if not silent:
                    self.log.info(f"Component configurations will be {verb}ed.")

                try:
                    await self._execute_component_actions(
                        config,
                        actions.components,
                        silent=silent,
                        strict=not reloading,
                    )

                    if not silent:
                        self.log.info(f"Component configurations {verb}ed successfully.")
                except Exception:
                    # A component that cannot be created fails the initial load outright, while
                    # a reload logs the failure and keeps the running engine alive.
                    if not reloading:
                        raise

                    self.log.error(
                        f"An issue occurred while {verb}ing components: {traceback.format_exc()}"
                    )

            # The server starts after the component tree exists so nothing binds a port until
            # the components have been created and validated.
            if actions.server is not None:
                if not silent:
                    self.log.info(f"Server configuration will be {verb}ed.")

                try:
                    await self._stop_server()
                    await self._start_server()
                    if not silent:
                        self.log.info(f"Server configuration {verb}ed successfully.")
                except Exception:
                    self.log.error(
                        f"An issue occurred while {verb}ing the server: {traceback.format_exc()}"
                    )

            # Synchronize each component's configuration in place. Components whose configuration
            # only changed in non-structural ways (those that don't require a recreate) pick up
            # the new values here.
            for component in self.get_components():
                component_config = config.get_component(component.system.address)
                if component_config is not None and component.system.config != component_config:
                    self.log.info(
                        f"Assigning new configuration in-place for '{component.system.address}'."
                    )
                    component.system.config = component_config

                component.system.sync_child_order()

            # Restart everything that was previously running. Newly created components that are
            # marked enabled will be started by their parent or by the top-level start cascade.
            for address in running:
                component = self.get_component(address)
                if component is not None:
                    component.system.start()

            self._loaded = True

        if not silent:
            self.log.info(f"{verb.capitalize()} completed.")

        return actions

    def _get_apply_actions(self, config: Config) -> EngineActions:
        if self._database.config != config.database:
            database = LoadPendingDatabaseConfigEngineAction()
        else:
            database = None

        if self._server is None or self._server.config != config.server:
            server = LoadPendingServerConfigEngineAction()
        else:
            server = None

        components: list[EngineComponentAction] = []
        names = uniq([*self._components.keys(), *(entry.name for entry in config.components)])
        for name in names:
            components.extend(self._get_pending_component_actions(config, Address(f"@{name}")))

        return EngineActions(
            database=database,
            server=server,
            components=components,
        )

    def _get_pending_component_actions(
        self,
        config: Config,
        address: Address,
    ) -> list[EngineComponentAction]:
        component = self.get_component(address)
        config_entry = config.get_component(address)

        match (component, config_entry):
            case (None, None):
                return []
            case (None, config_entry):
                return [CreateComponentEngineAction(address=address)]
            case (component, None):
                return [RemoveComponentEngineAction(address=address)]
            case (component, config_entry):
                pass

        # Compare configurations excluding the children, structural differences in the subtree
        # are handled per-child below.
        exclude = {"components"}
        old = (
            {}
            if component.system.config is None
            else dump(component.system.config, exclude=exclude)
        )
        new = dump(config_entry, exclude=exclude)

        if old != new:
            # When a component's own configuration changes, anything that holds a reference to it
            # also needs recreating so the reference rebinds to the new instance, unless the
            # referencer is itself part of the recreated subtree.
            affected = [address]
            for referencer in component.system.get_referencing_components(recursive=True):
                if not address.contains(referencer.system.address):
                    affected.append(referencer.system.address)

            return [RecreateComponentEngineAction(address=address) for address in affected]

        # Recurse over the union of present children and configured children so we catch both
        # additions and removals.
        actions: list[EngineComponentAction] = []
        children = uniq(
            [child.address for child in component.system.children]
            + [component.system.address / child.name for child in config_entry.components]
        )

        for child in children:
            actions.extend(self._get_pending_component_actions(config, child))

        return actions

    async def _execute_component_actions(
        self,
        config: Config,
        actions: Sequence[EngineComponentAction],
        *,
        silent: bool = False,
        strict: bool = False,
    ) -> None:
        creation_errors: list[ComponentError] = []
        for action in actions:
            parent_address = action.address.parent
            if parent_address is None:
                container: ComponentSystem | Engine = self
            else:
                parent = self.get_component(parent_address)
                container = parent.system if parent is not None else self

            component = self.get_component(action.address)
            config_entry = config.get_component(action.address)

            match action:
                case CreateComponentEngineAction():
                    if not silent:
                        self.log.info(f"Creating '{action.address}'.")

                    if config_entry is None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' not found in configuration. Skipping."
                            )

                        continue

                    if component is not None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' already exists. Skipping."
                            )

                        continue

                    try:
                        component = config_entry.create(container)
                        for current in component.system.get_components(inclusive=True):
                            if not silent:
                                self.log.info(
                                    f"Created '{current.system.address}' as instance of {type(current)}."
                                )
                    except Error as error:
                        errors = self._unwrap_component_errors(error)
                        creation_errors.extend(errors)
                        if not silent:
                            self.log.error(
                                f"Failed to create '{action.address}'. Errors: {to_json(errors, indent=2)}"
                            )
                case RecreateComponentEngineAction():
                    self.log.info(f"Recreating '{action.address}'.")
                    if config_entry is None:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' not found in configuration. Skipping."
                            )

                        continue

                    if component is not None:
                        if not silent:
                            self.log.info(f"Stopping '{action.address}'.")

                        await component.system.stop()
                        component.system.detach()
                    else:
                        if not silent:
                            self.log.warning(
                                f"Component at '{action.address}' does not exist. Creating."
                            )

                    try:
                        component = config_entry.create(container)
                        for current in component.system.get_components(inclusive=True):
                            if not silent:
                                self.log.info(
                                    f"Recreated '{current.system.address}' as instance of {type(current)}."
                                )
                    except Error as error:
                        errors = self._unwrap_component_errors(error)
                        creation_errors.extend(errors)
                        if not silent:
                            self.log.error(
                                f"Failed to recreate '{action.address}'. Errors: {to_json(errors, indent=2)}"
                            )
                case RemoveComponentEngineAction():
                    if component is not None:
                        if not silent:
                            self.log.info(f"Stopping '{action.address}'.")

                        await component.system.stop()
                        component.system.detach()

                        if not silent:
                            self.log.info(f"Removed '{action.address}'.")
                    else:
                        if not silent:
                            self.log.warning(
                                f"Component at {action.address} does not exist to remove. Skipping."
                            )

        if strict and creation_errors:
            raise ComponentCombinedError(errors=creation_errors)

    @staticmethod
    def _unwrap_component_errors(error: Error) -> list[ComponentError]:
        """Flatten `error` into a list of component errors, wrapping unexpected kinds."""
        if isinstance(error, ComponentCombinedError):
            return list(error.errors)

        return [ComponentUnexpectedError(exception=trace(error))]
