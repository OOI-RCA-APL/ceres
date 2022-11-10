import asyncio
import inspect
import traceback
from dataclasses import dataclass
from logging import ERROR, INFO, WARNING, Logger
from multiprocessing.managers import BaseManager
from threading import Lock
from types import MappingProxyType
from typing import Any, Mapping, Protocol, cast
from uuid import UUID

from pydantic import validate_arguments

from ..address import ComponentAddress, LocalComponentAddress, UnitAddress
from ..alert import Alert, AlertLevel
from ..component import Component
from ..config import Config, UnitConfig
from ..events import AlertEmittedEvent, Event, MessageReceivedEvent, MessageSentEvent
from ..message import Message, MessageDirection
from ..result import Fail, Ok
from ..utilities import awaitify, jsonify
from . import logs
from .component import (
    ComponentHandle,
    ComponentHandleContext,
    ConnectionHandle,
    DriverHandle,
    NotifierHandle,
)
from .database.buffer import EntityBuffer
from .database.entity import AlertEntity, MessageEntity
from .database.manager import DatabaseManager
from .tasklet import Tasklet
from .utilities import setup_event_loop, strify, unreachable


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    address: UnitAddress
    root_config: Config
    unit_config: UnitConfig

    def __post_init__(self) -> None:
        assert self.root_config.get_unit(self.address)
        assert self.unit_config in self.root_config.units


class UnitProxyProtocol(Protocol):
    def rpc_run(self) -> BaseException | None:
        ...

    def rpc_stop(self) -> BaseException | None:
        ...

    def rpc_call_action(
        self,
        address: LocalComponentAddress,
        action: str,
        arguments: Mapping[str, Any],
    ) -> BaseException | None:
        ...

    def rpc_call_query(
        self,
        address: LocalComponentAddress,
        query: str,
        arguments: Mapping[str, Any],
    ) -> BaseException | None:
        ...


class Unit(UnitProxyProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = DatabaseManager(self._context.root_config.database)
        self._components: dict[str, ComponentHandle[Component]] = {}
        self._loop = setup_event_loop()
        self._message_buffer = EntityBuffer(
            MessageEntity,
            2500,
            self._database,
            self.logger,
        )
        self._alert_buffer = EntityBuffer(
            AlertEntity,
            2500,
            self._database,
            self.logger,
        )

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def address(self) -> UnitAddress:
        return self._context.address

    @property
    def config(self) -> UnitConfig:
        return self._context.unit_config

    @property
    def database(self) -> DatabaseManager:
        return self._database

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.address))

    @property
    def components(self) -> Mapping[str, ComponentHandle[Component]]:
        return MappingProxyType(self._components)

    def get_component_handle(
        self,
        address: str | LocalComponentAddress,
    ) -> ComponentHandle[Component] | None:
        return self._components.get(address if isinstance(address, str) else address.name)

    async def dispatch_event(self, event: Event) -> None:
        for component in self.components.values():
            if not component.instance:
                continue

            try:
                component.instance.handle_event(event)
            except Exception:
                self.logger.error(
                    f"{component.address} raised exception while handling event {event}: {traceback.format_exc()}"
                )

        match event:
            case MessageSentEvent() | MessageReceivedEvent():
                await self._handle_message(event.message)
            case AlertEmittedEvent():
                await self._handle_alert(event.alert)
            case _:
                pass

    async def _handle_message(self, message: Message) -> None:
        await self._message_buffer.add(
            MessageEntity(
                id=message.id,
                connection_id=message.connection_id,
                timestamp=message.timestamp,
                direction=MessageDirection.RECEIVE,
                content=message.content,
            )
        )

    async def _handle_alert(self, alert: Alert) -> None:
        match alert.level:
            case AlertLevel.INFO:
                log_level = INFO
            case AlertLevel.WARNING:
                log_level = WARNING
            case AlertLevel.ERROR:
                log_level = ERROR
            case _:
                raise ValueError(alert.level)

        origin = next(
            (
                component
                for component in self.components.values()
                if component.id == alert.origin_id
            ),
            None,
        )

        logger = origin.logger if origin else self.logger
        logger.log(
            log_level,
            f"ALERT({alert.kind}{' ' + jsonify(alert.info) if alert.info else ''})",
        )

        await self._alert_buffer.add(
            AlertEntity(
                id=alert.id,
                origin_id=alert.origin_id,
                timestamp=alert.timestamp,
                level=alert.level,
                kind=alert.kind,
                info=alert.info,
            )
        )

    def rpc_run(self) -> BaseException | None:
        try:
            self._loop.run_until_complete(self.run())
        except BaseException as exception:
            return exception

        return None

    def rpc_stop(self) -> BaseException | None:
        return asyncio.run_coroutine_threadsafe(self.stop(), self._loop).exception()

    def rpc_call_action(
        self,
        address: LocalComponentAddress,
        action: str,
        arguments: Mapping[str, Any],
    ) -> BaseException | Any:
        future = asyncio.run_coroutine_threadsafe(
            self.call_action(address, action, arguments),
            self._loop,
        )

        try:
            return future.result()
        except BaseException as exception:
            return exception

    def rpc_call_query(
        self,
        address: LocalComponentAddress,
        query: str,
        arguments: Mapping[str, Any],
    ) -> BaseException | Any:
        future = asyncio.run_coroutine_threadsafe(
            self.call_query(address, query, arguments),
            self._loop,
        )

        try:
            return future.result()
        except BaseException as exception:
            return exception

    async def call_action(
        self,
        address: LocalComponentAddress,
        action: str,
        arguments: Mapping[str, Any],
    ) -> Any:
        if (component := self.get_component_handle(address)) is None:
            raise ValueError(f"component at {address} does not exist")
        if component.instance is None:
            raise ValueError(f"component at {address} is not loaded")

        instance = component.instance
        if (binding := instance.get_action_bindings().get(action)) is None:
            raise ValueError(
                f"component of type {strify(type(component))} at {address} has no action named '{action}'"
            )

        if (
            method := getattr(instance, binding.function.__name__, None)
        ) is None or not inspect.ismethod(method):
            raise ValueError(
                f"component of type {strify(type(instance))} at address {address} has no method named '{action}' "
            )

        result = await awaitify(validate_arguments(method)(**arguments))
        return result

    async def call_query(
        self,
        address: LocalComponentAddress,
        query: str,
        arguments: Mapping[str, Any],
    ) -> Any:
        if (component := self.get_component_handle(address)) is None:
            raise ValueError(f"component at {address} does not exist")
        if component.instance is None:
            raise ValueError(f"component at {address} is not loaded")

        instance = component.instance
        if (binding := instance.get_query_bindings().get(query)) is None:
            raise ValueError(
                f"component of type {strify(type(component))} at {address} has no query named '{query}'"
            )

        if (
            method := getattr(instance, binding.function.__name__, None)
        ) is None or not inspect.ismethod(method):
            raise ValueError(
                f"component of type {strify(type(instance))} at address {address} has no method named '{query}' "
            )

        result = await awaitify(validate_arguments(method)(**arguments))
        return result

    async def __run__(self) -> None:
        await self._load_components()

        for component in self.components.values():
            component.start(
                on_exception=self._on_component_exception,
                on_completed=self._on_component_completed,
            )

        await asyncio.gather(
            self._process_message_buffer(),
            self._process_alert_buffer(),
        )

    async def _process_message_buffer(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if not self._message_buffer.flushing:
                await self._message_buffer.flush()

    async def _process_alert_buffer(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if not self._alert_buffer.flushing:
                await self._alert_buffer.flush()

    async def __stop__(self) -> None:
        for component in self.components.values():
            await component.stop()
        await self._database.dispose()

    async def _load_components(self) -> None:
        for component_config in self.config.components:
            address = ComponentAddress(self.address.name, component_config.name)

            if component_config.name in self._components:
                continue

            id = await self._database.entities.get_address_id(address)

            match component_config.kind:
                case "connection":
                    cls: type[ComponentHandle[Any]] = ConnectionHandle
                case "driver":
                    cls = DriverHandle
                case "notifier":
                    cls = NotifierHandle
                case _:
                    unreachable()

            self._components[component_config.name] = cls(
                ComponentHandleContext(
                    id=id,
                    address=address,
                    root_config=self._context.root_config,
                    unit_config=self.config,
                    component_config=component_config,
                    unit=self,
                )
            )

        for handle in self._components.values():
            match await handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{handle.address}' as {strify(type(handle.instance))} with id '{handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load component '{handle.address}'. Error: {jsonify(error, indent=2)}"
                    )

    def _on_component_exception(
        self,
        component: ComponentHandle[Component],
        exception: BaseException,
    ) -> None:
        self.logger.error(
            f"Exception occurred in component '{component.address}': {traceback.format_exception(exception)}"
        )

    def _on_component_completed(self, component: ComponentHandle[Component]) -> None:
        self.logger.info(f"Component '{component.address}' completed execution.")


class UnitManager(BaseManager):
    pass


UnitManager.register("Unit", Unit)


class UnitHandle(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._manager: UnitManager | None = None
        self._instance: UnitProxyProtocol | None = None
        self._lock = Lock()

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def address(self) -> UnitAddress:
        return self._context.address

    @property
    def config(self) -> UnitConfig:
        return next(
            unit for unit in self._context.root_config.units if unit.name == self.address.name
        )

    @property
    def instance(self) -> UnitProxyProtocol | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.address))

    async def __run__(self) -> None:
        def execute() -> None:
            with self._lock:
                self._manager = UnitManager()
                self._manager.start()
                instance = cast(UnitProxyProtocol, cast(Any, self._manager).Unit(self._context))
                self._instance = instance

            try:
                result = instance.rpc_run()
            except EOFError:
                result = None
                pass

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running unit '{self.address}': {strify(result)}"
                )

        await asyncio.to_thread(execute)

    async def __stop__(self) -> None:
        def execute() -> None:
            with self._lock:
                if self._instance:
                    try:
                        result = self._instance.rpc_stop()
                    except EOFError:
                        result = None
                        pass
                    finally:
                        self._instance = None
                else:
                    result = None

                if self._manager:
                    self._manager.shutdown()

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while stopping unit '{self.address}': {strify(result)}"
                )

        await asyncio.to_thread(execute)

    async def call_action(
        self,
        address: LocalComponentAddress,
        action: str,
        arguments: Mapping[str, Any],
    ) -> Any:
        def execute() -> Any:
            if self.instance is None:
                raise ValueError(f"unit at {address} is not loaded")

            result = self.instance.rpc_call_action(address, action, arguments)
            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running calling action '{action}' on component '{self.address}': {strify(result)}"
                )
                raise result

            return result

        return await asyncio.to_thread(execute)

    async def call_query(
        self,
        address: LocalComponentAddress,
        query: str,
        arguments: Mapping[str, Any],
    ) -> Any:
        def execute() -> Any:
            if self.instance is None:
                raise ValueError(f"unit at {address} is not loaded")

            result = self.instance.rpc_call_query(address, query, arguments)
            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running calling action '{query}' on component '{self.address}': {strify(result)}"
                )
                raise result

            return result

        return await asyncio.to_thread(execute)
