import asyncio
import threading
import traceback
from asyncio import Queue as AsyncQueue
from dataclasses import dataclass, field
from logging import Logger
from multiprocessing.managers import SyncManager
from queue import Queue as ThreadSafeQueue
from threading import Lock
from types import MappingProxyType
from typing import Any, AsyncIterable, Mapping, Protocol, cast, final
from uuid import UUID, uuid4

from ..address import LocalComponentAddress, UnitAddress, caddr
from ..component import CallableProcedureKind, SubscribableProcedureKind
from ..config import ConcurrencyKind, Config, UnitConfig
from ..data import jsonify
from ..database import Database
from ..errors import (
    ProcedureComponentNotLoadedError,
    ProcedureDoesNotExistError,
    ProcedureError,
    ProcedureExceptionError,
)
from ..result import Fail, Ok, Result
from . import logs
from .component import ComponentHandle, ComponentHandleContext
from .tasklet import Tasklet
from .utilities import (
    QueueLike,
    ensure_event_loop,
    get_or_cancel,
    sleep_forever,
    spawn,
    strify,
)


@dataclass(kw_only=True, frozen=True)
class UnitContext:
    id: UUID
    address: UnitAddress
    root_config: Config
    unit_config: UnitConfig
    database: Database | None = None

    def __post_init__(self) -> None:
        assert self.root_config.get_unit(self.address)
        assert self.unit_config in self.root_config.units


@dataclass(kw_only=True, frozen=True)
class Subscriber:
    subscription_id: UUID = field(default_factory=uuid4)
    queue: QueueLike[object | None]


@dataclass(kw_only=True, frozen=True)
class Subscription:
    id: UUID
    queue: asyncio.Queue[object | None]
    task: asyncio.Task[object]
    cancelled: threading.Event


@dataclass(kw_only=True, frozen=True)
class SubscriptionFeed:
    task: asyncio.Task[None]


class UnitRemoteProtocol(Protocol):
    def remote_run(self) -> None | BaseException:
        ...

    def remote_stop(self) -> None | BaseException:
        ...

    def remote_call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError] | BaseException:
        ...

    def remote_subscribe(
        self,
        subscriber: Subscriber,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[None, ProcedureError] | BaseException:
        ...

    def remote_unsubscribe(self, subscriber_id: UUID) -> None:
        ...


@final
class Unit(UnitRemoteProtocol, Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__database = context.database or Database(self.__context.root_config.database)
        self.__loop = ensure_event_loop()
        self.__component_handles: dict[str, ComponentHandle] = {}
        self.__subscription_feeds: dict[UUID, SubscriptionFeed] = {}

    @property
    def id(self) -> UUID:
        return self.__context.id

    @property
    def address(self) -> UnitAddress:
        return self.__context.address

    @property
    def config(self) -> UnitConfig:
        return self.__context.unit_config

    @property
    def database(self) -> Database:
        return self.__database

    @property
    def concurrency(self) -> ConcurrencyKind:
        return (
            self.__context.unit_config.concurrency or self.__context.root_config.runtime.concurrency
        )

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.__context.address))

    @property
    def components(self) -> Mapping[str, ComponentHandle]:
        return MappingProxyType(self.__component_handles)

    def get_component_handle(self, address: LocalComponentAddress) -> ComponentHandle | None:
        return self.__component_handles.get(address if isinstance(address, str) else address.name)

    def remote_run(self) -> None | BaseException:
        try:
            if self.__loop.is_running():
                asyncio.run_coroutine_threadsafe(self.run(), self.__loop).exception()
            else:
                self.__loop.run_until_complete(self.run())
        except BaseException as exception:
            self.logger.error(f"An exception occurred while running: {traceback.format_exc()}")
            return exception

        return None

    def remote_stop(self) -> None | BaseException:
        return asyncio.run_coroutine_threadsafe(self.stop(), self.__loop).exception()

    def remote_call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError] | BaseException:
        future = asyncio.run_coroutine_threadsafe(
            self.call(address, kind, procedure, input),
            self.__loop,
        )

        try:
            return future.result()
        except BaseException as exception:
            return exception

    def remote_subscribe(
        self,
        subscriber: Subscriber,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[None, ProcedureError] | BaseException:
        async def subscribe() -> Result[SubscriptionFeed, ProcedureError]:
            match await self.subscribe(address, kind, procedure, input):
                case Ok(values):
                    pass
                case Fail() as fail:
                    return fail

            async def enqueue() -> None:
                try:
                    async for value in values:
                        subscriber.queue.put_nowait(value)
                except Exception:
                    self.logger.error(
                        f"An exception occurred in subscription: {traceback.format_exc()}"
                    )

            return Ok(SubscriptionFeed(task=asyncio.create_task(enqueue())))

        future = asyncio.run_coroutine_threadsafe(subscribe(), self.__loop)

        try:
            match future.result():
                case Ok(feed):
                    pass
                case Fail() as fail:
                    return fail
        except BaseException as exception:
            return exception

        self.__subscription_feeds[subscriber.subscription_id] = feed
        return Ok(None)

    def remote_unsubscribe(self, subscriber_id: UUID) -> None:
        try:
            if (subscription := self.__subscription_feeds.pop(subscriber_id, None)) is not None:
                subscription.task.cancel()
        except Exception:
            traceback.print_exc()

    async def call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        if (component := self.get_component_handle(address)) is None:
            return Fail(ProcedureDoesNotExistError())
        if component.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await component.instance.call(kind, procedure, input)

    async def subscribe(
        self,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[AsyncIterable[object | None], ProcedureError]:
        if (component := self.get_component_handle(address)) is None:
            return Fail(ProcedureDoesNotExistError())
        if component.instance is None:
            return Fail(ProcedureComponentNotLoadedError())

        return await component.instance.subscribe(kind, procedure, input)

    async def __run__(self) -> None:
        await self.__load_components()

        for component in self.components.values():
            component.start(
                on_exception=self.__on_component_exception,
                on_completed=self.__on_component_completed,
            )

        await sleep_forever()

    async def __stop__(self) -> None:
        async def stop() -> None:
            try:
                for component in reversed(self.components.values()):
                    self.logger.info(f"Stopping component '{component.address}'...")
                    await component.stop()

                for feed in self.__subscription_feeds.values():
                    feed.task.cancel()
                self.__subscription_feeds.clear()
            finally:
                if self.__context.database is None:
                    await self.__database.dispose()

        await asyncio.shield(asyncio.create_task(stop()))

    async def __load_components(self) -> None:
        for component_config in self.config.components:
            address = caddr(self.address.name, component_config.name)

            if component_config.name in self.__component_handles:
                continue

            id = await self.__database.entities.get_address_id(address)

            self.__component_handles[component_config.name] = ComponentHandle(
                ComponentHandleContext(
                    id=id,
                    address=address,
                    root_config=self.__context.root_config,
                    unit_config=self.config,
                    component_config=component_config,
                    unit=self,
                )
            )

        for component_handle in self.__component_handles.values():
            match await component_handle.load():
                case Ok():
                    self.logger.info(
                        f"Loaded '{component_handle.address}' as {strify(type(component_handle.instance))} with id '{component_handle.id}'."
                    )
                case Fail(error):
                    self.logger.error(
                        f"Failed to load component '{component_handle.address}'. Error: {jsonify(error, indent=2)}"
                    )

    def __on_component_exception(self, handle: ComponentHandle, exception: BaseException) -> None:
        self.logger.error(
            f"Exception occurred in component '{handle.address}': {traceback.format_exception(exception)}"
        )

    def __on_component_completed(self, handle: ComponentHandle) -> None:
        self.logger.info(f"Component '{handle.address}' stopped.")


@final
class UnitProcess(SyncManager):
    pass


UnitProcess.register("Unit", Unit)


@final
class UnitHandle(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__process: UnitProcess | None = None
        self.__instance: UnitRemoteProtocol | None = None
        self.__lock = Lock()

    @property
    def id(self) -> UUID:
        return self.__context.id

    @property
    def address(self) -> UnitAddress:
        return self.__context.address

    @property
    def config(self) -> UnitConfig:
        return next(
            unit for unit in self.__context.root_config.units if unit.name == self.address.name
        )

    @property
    def instance(self) -> UnitRemoteProtocol | None:
        return self.__instance

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.address))

    @property
    def concurrency(self) -> ConcurrencyKind:
        return (
            self.__context.unit_config.concurrency or self.__context.root_config.runtime.concurrency
        )

    async def __run__(self) -> None:
        def execute() -> None:
            with self.__lock:
                if self.concurrency == ConcurrencyKind.PROCESS:
                    self.__process = UnitProcess()
                    self.__process.start()
                    self.__instance = cast(
                        UnitRemoteProtocol, cast(Any, self.__process).Unit(self.__context)
                    )
                else:
                    self.__instance = Unit(self.__context)

            try:
                result = self.__instance.remote_run()
            except EOFError:
                result = None

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running unit '{self.address}': {strify(traceback.format_exception(result))}"
                )

        await spawn(execute)

    async def __stop__(self) -> None:
        def execute() -> None:
            with self.__lock:
                if self.__instance:
                    try:
                        result = self.__instance.remote_stop()
                    except EOFError:
                        result = None
                    finally:
                        self.__instance = None
                else:
                    result = None

                if self.__process:
                    self.__process.shutdown()

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while stopping unit '{self.address}': {strify(result)}"
                )

        await spawn(execute)

    async def call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        def execute() -> Result[object | None, ProcedureError]:
            if self.instance is None:
                return Fail(ProcedureComponentNotLoadedError())

            try:
                result = self.instance.remote_call(address, kind, procedure, input)
            except EOFError:
                return Fail(ProcedureComponentNotLoadedError())

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running calling {kind} '{procedure}' on component '{self.address}': {strify(result)}"
                )
                return Fail(ProcedureExceptionError(traceback=traceback.format_exception(result)))

            return result

        return await spawn(execute)

    async def subscribe(
        self,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[Subscription, ProcedureError]:
        if self.instance is None or (
            self.concurrency == ConcurrencyKind.PROCESS and self.__process is None
        ):
            return Fail(ProcedureComponentNotLoadedError())

        instance = self.instance

        match self.concurrency:
            case ConcurrencyKind.PROCESS:
                queue = cast(Any, self.__process).Queue()
            case ConcurrencyKind.THREAD:
                queue = cast(Any, ThreadSafeQueue())

        subscriber = Subscriber(queue=queue)

        def subscribe() -> Result[None, ProcedureError]:
            try:
                result = instance.remote_subscribe(subscriber, address, kind, procedure, input)
            except EOFError:
                return Fail(ProcedureComponentNotLoadedError())
            except Exception:
                return Fail(ProcedureExceptionError(traceback=traceback.format_exc()))

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while getting {kind} '{procedure}' on component '{self.address}': {strify(result)}"
                )
                return Fail(ProcedureExceptionError(traceback=traceback.format_exception(result)))

            return result

        match await spawn(subscribe):
            case Ok():
                pass
            case Fail() as fail:
                return fail

        cancelled = threading.Event()

        async def dequeue() -> None:
            def get() -> object | None:
                return get_or_cancel(subscriber.queue, cancelled)

            while True:
                await asyncio.sleep(0)
                value = await spawn(get)
                subscription.queue.put_nowait(value)

        task = asyncio.create_task(dequeue())

        subscription = Subscription(
            id=subscriber.subscription_id,
            queue=AsyncQueue(),
            task=task,
            cancelled=cancelled,
        )

        self.logger.info(f"Subscribed: {subscription.id}")
        return Ok(subscription)

    async def unsubscribe(self, subscription: Subscription) -> None:
        if not self.instance:
            return

        try:
            await spawn(self.instance.remote_unsubscribe, subscription.id)
            self.logger.info(f"Unsubscribed: {subscription.id}")
        finally:
            subscription.task.cancel()
            subscription.cancelled.set()
