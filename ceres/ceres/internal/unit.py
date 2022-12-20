import asyncio
import threading
import traceback
from asyncio import Queue as AsyncQueue
from asyncio import Task
from logging import Logger
from multiprocessing.managers import SyncManager
from queue import Empty, Queue
from typing import Any, AsyncIterator, cast, final
from uuid import UUID, uuid4

from ..address import LocalComponentAddress, UnitAddress
from ..config import ConcurrencyKind, UnitConfig
from ..errors import (
    ProcedureComponentNotLoadedError,
    ProcedureError,
    ProcedureExceptionError,
)
from ..procedure import CallableProcedureKind, SubscribableProcedureKind
from ..result import Fail, Ok, Result
from ..unit import Unit, UnitContext
from . import logs
from .tasklet import Tasklet
from .utilities import QueueLike, ensure_event_loop, spawn, strify

SubscriptionIntermediateQueue = QueueLike[object]
SubscriptionResultsQueue = AsyncQueue[object]


class Subscription(AsyncIterator[object]):
    def __init__(
        self,
        *,
        id: UUID,
        queue: SubscriptionResultsQueue,
    ) -> None:
        self.__id = id
        self.__queue = queue

    @property
    def id(self) -> UUID:
        return self.__id

    def __aiter__(self) -> AsyncIterator[object]:
        return self

    async def __anext__(self) -> object:
        return await self.get()

    async def get(self) -> object:
        value = await self.__queue.get()
        self.__queue.task_done()
        return value


class UnitProxy:
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__unit = Unit(context)
        self.__loop = ensure_event_loop()
        self.__subscription_tasks: dict[UUID, Task[None]] = {}

    @property
    def logger(self) -> Logger:
        return logs.get(str(self.__context.address))

    def run(self) -> None | BaseException:
        try:
            if self.__loop.is_running():
                asyncio.run_coroutine_threadsafe(self.__unit.run(), self.__loop).exception()
            else:
                self.__loop.run_until_complete(self.__unit.run())
        except BaseException as exception:
            self.logger.error(f"An exception occurred while running: {traceback.format_exc()}")
            return exception

        return None

    def stop(self) -> None | BaseException:
        for task in self.__subscription_tasks.values():
            task.cancel()

        self.__subscription_tasks.clear()
        return asyncio.run_coroutine_threadsafe(self.__unit.stop(), self.__loop).exception()

    def call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError] | BaseException:
        future = asyncio.run_coroutine_threadsafe(
            self.__unit.call(address, kind, procedure, input),
            self.__loop,
        )

        try:
            return future.result()
        except BaseException as exception:
            return exception

    def subscribe(
        self,
        queue: SubscriptionIntermediateQueue,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[UUID, ProcedureError] | BaseException:
        async def subscribe() -> Result[Task[None], ProcedureError]:
            match await self.__unit.subscribe(address, kind, procedure, input):
                case Ok(values):
                    pass
                case Fail() as fail:
                    return fail

            async def enqueue() -> None:
                try:
                    async for value in values:
                        queue.put_nowait(value)
                except Exception:
                    self.logger.error(
                        f"An exception occurred in subscription: {traceback.format_exc()}"
                    )

            return Ok(asyncio.create_task(enqueue()))

        future = asyncio.run_coroutine_threadsafe(subscribe(), self.__loop)

        try:
            match future.result():
                case Ok(task):
                    pass
                case Fail() as fail:
                    return fail
        except BaseException as exception:
            return exception

        subscription_id = uuid4()
        self.__subscription_tasks[subscription_id] = task
        return Ok(subscription_id)

    def unsubscribe(self, subscription_id: UUID) -> None | BaseException:
        try:
            if (task := self.__subscription_tasks.pop(subscription_id, None)) is not None:
                task.cancel()
        except BaseException as exception:
            return exception


@final
class UnitProcess(SyncManager):
    pass


UnitProcess.register("UnitProxy", UnitProxy)


@final
class UnitHandle(Tasklet):
    def __init__(self, context: UnitContext) -> None:
        self.__context = context
        self.__process: UnitProcess | None = None
        self.__proxy: UnitProxy | None = None
        self.__lock = threading.Lock()
        self.__subscription_tasks: dict[UUID, Task[object]] = {}

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
    def logger(self) -> Logger:
        return logs.get(str(self.address))

    @property
    def concurrency(self) -> ConcurrencyKind:
        return (
            self.__context.unit_config.concurrency or self.__context.root_config.runtime.concurrency
        )

    async def __run__(self) -> None:
        def thread() -> None:
            with self.__lock:
                if self.concurrency == ConcurrencyKind.PROCESS:
                    self.__process = UnitProcess()
                    self.__process.start()
                    self.__proxy = cast(
                        UnitProxy, cast(Any, self.__process).UnitProxy(self.__context)
                    )
                else:
                    self.__proxy = UnitProxy(self.__context)

            try:
                result = self.__proxy.run()
            except EOFError:
                result = None

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running unit '{self.address}': {strify(traceback.format_exception(result))}"
                )

        await spawn(thread)

    async def __stop__(self) -> None:
        def thread() -> None:
            with self.__lock:
                if self.__proxy:
                    try:
                        result = self.__proxy.stop()
                    except EOFError:
                        result = None
                    finally:
                        self.__proxy = None
                else:
                    result = None

                if self.__process:
                    self.__process.shutdown()

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while stopping unit '{self.address}': {strify(result)}"
                )

        await spawn(thread)

    async def call(
        self,
        address: LocalComponentAddress,
        kind: CallableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[object | None, ProcedureError]:
        def thread() -> Result[object | None, ProcedureError]:
            if self.__proxy is None:
                return Fail(ProcedureComponentNotLoadedError())

            try:
                result = self.__proxy.call(address, kind, procedure, input)
            except EOFError:
                return Fail(ProcedureComponentNotLoadedError())

            if isinstance(result, BaseException):
                self.logger.error(
                    f"Exception occurred while running calling {kind} '{procedure}' on component '{self.address}': {strify(result)}"
                )
                return Fail(ProcedureExceptionError(traceback=traceback.format_exception(result)))

            return result

        return await spawn(thread)

    async def subscribe(
        self,
        address: LocalComponentAddress,
        kind: SubscribableProcedureKind,
        procedure: str,
        input: object | None = None,
    ) -> Result[Subscription, ProcedureError]:
        if self.__proxy is None or (
            self.concurrency == ConcurrencyKind.PROCESS and self.__process is None
        ):
            return Fail(ProcedureComponentNotLoadedError())

        proxy = self.__proxy

        match self.concurrency:
            case ConcurrencyKind.PROCESS:
                intermediate: SubscriptionIntermediateQueue = cast(Any, self.__process).Queue()
            case ConcurrencyKind.THREAD:
                intermediate = cast(Any, Queue())

        def subscribe() -> Result[UUID, ProcedureError]:
            try:
                result = proxy.subscribe(intermediate, address, kind, procedure, input)
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
            case Ok(id):
                pass
            case Fail() as fail:
                return fail

        results = AsyncQueue()

        async def bridge() -> None:
            def get() -> object:
                # TODO: Find a way to do this without polling.
                while not task.done():
                    try:
                        return intermediate.get(timeout=1)
                    except Empty:
                        pass

            while True:
                await asyncio.sleep(0)
                value = await spawn(get)
                results.put_nowait(value)

        task = asyncio.create_task(bridge())

        self.__subscription_tasks[id] = task
        subscription = Subscription(id=id, queue=results)

        self.logger.info(f"Subscribed: {subscription.id}")
        return Ok(subscription)

    async def unsubscribe(self, subscription: Subscription) -> None:
        task = self.__subscription_tasks.get(subscription.id)
        if task is not None:
            task.cancel()

        if not self.__proxy:
            return

        await spawn(self.__proxy.unsubscribe, subscription.id)
        self.logger.info(f"Unsubscribed: {subscription.id}")
