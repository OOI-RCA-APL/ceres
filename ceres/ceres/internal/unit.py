import asyncio
import traceback
from dataclasses import dataclass
from logging import ERROR, INFO, WARNING, Logger
from multiprocessing.managers import BaseManager
from threading import Event as ThreadEvent
from threading import Lock
from typing import Any, Iterable, Protocol, cast
from uuid import UUID

from ..address import ComponentAddress, LocalComponentAddress, UnitAddress
from ..alert import Alert, AlertLevel
from ..config import Config, UnitConfig
from ..events import Event
from ..result import Fail, Ok
from . import logs
from .component import ComponentHandle, ComponentHandleContext, ComponentHandleInterface
from .connection import ConnectionHandle
from .database.entity import AlertEntity
from .database.manager import DatabaseManager
from .driver import DriverHandle
from .notifier import NotifierHandle
from .tasks import Tasklet, ensure_event_loop
from .utilities import jsonify, run_in_thread, unreachable, unwrap


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    address: UnitAddress
    config: Config


class UnitProxyProtocol(Protocol):
    def rpc_run(self) -> BaseException | None:
        ...

    def rpc_stop(self) -> BaseException | None:
        ...


class Unit(UnitProxyProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self._context = context
        self._database = DatabaseManager(self._context.config.database)
        self._components: dict[str, ComponentHandleInterface] = {}

        self._loop = ensure_event_loop()
        self._stopping = ThreadEvent()
        self._stopped = ThreadEvent()

    @property
    def id(self) -> UUID:
        return self._context.id

    @property
    def address(self) -> UnitAddress:
        return self._context.address

    @property
    def config(self) -> UnitConfig:
        return unwrap(self._context.config.get_unit(self.address))

    @property
    def database(self) -> DatabaseManager:
        return self._database

    @property
    def logger(self) -> Logger:
        return logs.get(str(self._context.address))

    @property
    def components(self) -> Iterable[ComponentHandleInterface]:
        return self._components.values()

    def get_component(
        self,
        address: str | LocalComponentAddress,
    ) -> ComponentHandleInterface | None:
        return self._components.get(address if isinstance(address, str) else address.name)

    async def handle_event(self, event: Event) -> None:
        for component in self.components:
            if component.instance:
                try:
                    await component.instance.handle_event(event)
                except Exception:
                    self.logger.error(
                        f"{component.address} raised exception while handling event {event}: {traceback.format_exc()}"
                    )

    async def handle_alert(self, alert: Alert) -> None:
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
            (component for component in self.components if component.id == alert.origin_id), None
        )

        logger = origin.logger if origin else self.logger
        logger.log(
            log_level,
            f"ALERT({alert.kind}{' ' + jsonify(alert.info) if alert.info else ''})",
        )

        async with self._database.session() as session:
            entity = AlertEntity(
                id=alert.id,
                origin_id=alert.origin_id,
                timestamp=alert.timestamp,
                level=alert.level,
                kind=alert.kind,
                info=alert.info,
            )

            session.add(entity)
            await session.commit()

    def rpc_run(self) -> BaseException | None:
        try:
            self._loop.run_until_complete(self.run())
        except BaseException as exception:
            return exception

        return None

    def rpc_stop(self) -> BaseException | None:
        self._stopping.set()
        self._stopped.wait()
        return None

    async def _tasklet_run(self) -> None:
        self._stopping.clear()
        self._stopped.clear()

        await self._load_components()

        for component in self.components:
            component.start(
                on_exception=self._on_component_exception,
                on_completed=self._on_component_completed,
            )

        while not self._stopping.is_set():
            await asyncio.sleep(0.1)

        for component in self.components:
            await component.stop()

    async def _tasklet_stop(self) -> None:
        try:
            await self._database.dispose()
        finally:
            self._stopped.set()

    async def _load_components(self) -> None:
        for config in self.config.components:
            address = ComponentAddress(self.address.name, config.name)

            if config.name in self._components:
                continue

            id = await self._database.entities.get_id(address)

            match config.kind:
                case "connection":
                    cls: type[ComponentHandle] = ConnectionHandle
                case "driver":
                    cls = DriverHandle
                case "notifier":
                    cls = NotifierHandle
                case _:
                    unreachable()

            self._components[config.name] = cls(
                ComponentHandleContext(
                    id=id,
                    address=address,
                    unit=self,
                    config=self._context.config,
                    database=self._database,
                )
            )

        for handle in self._components.values():
            match await handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{handle.address}' as {type(handle.instance)} with id '{handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load component '{handle.address}'. Error: {jsonify(error, indent=2)}"
                    )

    def _on_component_exception(self, component: ComponentHandle, exception: BaseException) -> None:
        self.logger.error(f"Exception occurred in component '{component.address}': {exception}")

    def _on_component_completed(self, component: ComponentHandle) -> None:
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
        return next(unit for unit in self._context.config.units if unit.name == self.address.name)

    @property
    def instance(self) -> UnitProxyProtocol | None:
        return self._instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.address))

    async def _tasklet_run(self) -> None:
        def execute() -> None:
            with self._lock:
                self._manager = UnitManager()
                self._manager.start()
                instance = cast(UnitProxyProtocol, cast(Any, self._manager).Unit(self._context))
                self._instance = instance

            try:
                exception = instance.rpc_run()
            except EOFError:
                return

            if exception:
                self.logger.error(f"Exception occurred in unit '{self.address}': {exception}")

        await run_in_thread(execute)

    async def _tasklet_stop(self) -> None:
        def execute() -> None:
            with self._lock:
                if self._instance:
                    exception = self._instance.rpc_stop()
                    self._instance = None
                else:
                    exception = None

                if self._manager:
                    self._manager.shutdown()

            if exception:
                raise exception

        await run_in_thread(execute)
