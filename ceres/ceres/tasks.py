import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop, Event, Task
from dataclasses import dataclass, field
from typing import Any, Optional, cast

import anyio
import uvloop


def ensure_event_loop() -> AbstractEventLoop:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        uvloop.install()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop


async def defer() -> None:
    await anyio.sleep(0.000001)


@dataclass
class TaskletInternal:
    task: Optional[Task[Any]] = None
    stop: Event = field(default_factory=Event)


TASKLET_INTERNAL_ATTRIBUTE_NAME = "__tasklet_internal__"


class Tasklet(ABC):
    @property
    def started(self) -> bool:
        return self.__tasklet__.task is not None

    @property
    def __tasklet__(self) -> TaskletInternal:
        if internal := self.__dict__.get(TASKLET_INTERNAL_ATTRIBUTE_NAME):
            return cast(TaskletInternal, internal)

        internal = TaskletInternal()
        self.__dict__[TASKLET_INTERNAL_ATTRIBUTE_NAME] = internal
        return internal

    def start(self) -> None:
        if self.__tasklet__.task:
            return

        self.__tasklet__.stop.clear()

        ensure_event_loop()

        def done(task: Task[Any]) -> None:
            self.__tasklet__.task = None
            self.__tasklet__.stop.set()

            if task.cancelled():
                return

            if exception := task.exception():
                raise exception

        self.__tasklet__.task = asyncio.create_task(self.execute())
        self.__tasklet__.task.add_done_callback(done)

    async def stop(self) -> None:
        if not self.__tasklet__.task or self.__tasklet__.stop.is_set():
            return

        try:
            await self.teardown()
        finally:
            self.__tasklet__.task.cancel()
            self.__tasklet__.task = None
            self.__tasklet__.stop.set()

    async def join(self) -> None:
        if not self.__tasklet__.task:
            return

        await self.__tasklet__.stop.wait()

    async def run(self) -> None:
        self.start()
        await self.join()

    @abstractmethod
    async def execute(self) -> None:
        ...

    async def teardown(self) -> None:
        pass
