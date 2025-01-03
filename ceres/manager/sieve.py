from __future__ import annotations

import asyncio
import traceback

from ceres._internal.lazy import lazy_imports
from ceres.data import Name
from ceres.error import ParticleError
from ceres.event import (
    ParticleEvent,
    SieveAddedEvent,
    SieveExceptionEvent,
    SieveParticleErrorEvent,
    SieveRemovedEvent,
    SieveRetryEvent,
    SieveRetryPendingEvent,
    SieveStartedEvent,
    SieveStoppedEvent,
)
from ceres.particle import Particle
from ceres.stream import WriteStream

with lazy_imports(__name__):
    from ceres._internal import util
    from ceres.component import ComponentSystem
    from ceres.config import SieveConfig


class SieveManager:
    __slots__ = (
        "_system",
        "_configs",
        "_runners",
        "_running",
        "_stopping",
        "_syncs",
    )

    def __init__(self, source: ComponentSystem) -> None:
        self._system = source
        self._configs: dict[Name, SieveConfig] = {}
        self._runners: dict[Name, asyncio.Task[None]] = {}
        self._running = False
        self._stopping = False
        self._syncs: WriteStream[SieveConfig] = WriteStream()

    @property
    def count(self) -> int:
        return len(self._configs)

    async def __run__(self) -> None:
        self._running = True
        try:
            await self.__sync_runners()
            await util.sleep_forever()
            async for _ in self._syncs:
                await self.__sync_runners()
        finally:
            self._stopping = True
            try:
                await util.cancel(self._runners.values())
                self._runners.clear()
            finally:
                self._running = False
                self._stopping = False

    def add(self, sieve: SieveConfig) -> None:
        assert sieve.name not in self._configs
        self._configs[sieve.name] = sieve
        self._system.events.emit(SieveAddedEvent, sieve=sieve.name)
        if self._running and not self._stopping:
            self._syncs.put(sieve)

    def get(self, name: Name) -> SieveConfig | None:
        return self._configs.get(name)

    def get_all(self) -> list[SieveConfig]:
        return list(self._configs.values())

    async def remove(self, name: Name) -> SieveConfig | None:
        runner = self._runners.get(name)
        if runner is not None:
            await util.cancel(runner)
            self._runners.pop(name, None)

        config = self._configs.pop(name, None)
        self._system.events.emit(SieveRemovedEvent, sieve=name)
        return config

    async def clear(self) -> None:
        await self.__clear_runners()
        self._configs.clear()

    async def __clear_runners(self) -> None:
        await util.cancel(self._runners.values())
        self._runners.clear()

    async def __remove_runner(self, name: Name) -> asyncio.Task[None] | None:
        runner = self._runners.get(name)
        if runner is not None:
            await util.cancel(runner)
            self._runners.pop(name, None)

        return runner

    async def __create_runner(self, config: SieveConfig) -> asyncio.Task[None]:
        runner = asyncio.create_task(self.__run(config), name=config.name + "-task")
        self._runners[config.name] = runner
        return runner

    async def __sync_runners(self) -> None:
        for config in self._configs.values():
            await self.__create_runner(config)

    async def __run(self, config: SieveConfig) -> None:
        self._system.events.emit(SieveStartedEvent, sieve=config.name)
        retry = 0

        try:
            sieve = config.create()
            while True:
                try:
                    async for current in sieve.read(
                        self._system.messages.follow(address=self._system.address)
                    ):
                        if isinstance(current, ParticleError):
                            self._system.events.emit(
                                SieveParticleErrorEvent,
                                sieve=config.name,
                                error=current,
                            )
                        elif isinstance(current, Particle):
                            self._system.particles.store(current)
                            self._system.events.emit(ParticleEvent, particle=current)
                except Exception as exception:
                    traceback.print_exc()
                    if config.retries is not None:
                        if retry >= config.retries:
                            break

                    self._system.events.emit(
                        SieveRetryPendingEvent,
                        sieve=config.name,
                        delay=config.retry_delay,
                    )
                    retry += 1

                    self._system.events.emit(
                        SieveExceptionEvent,
                        sieve=config.name,
                        traceback=util.get_traceback(exception),
                    )
                    await asyncio.sleep(config.retry_delay.total_seconds())
                    self._system.events.emit(SieveRetryEvent, sieve=config.name)
        finally:
            self._system.events.emit(SieveStoppedEvent, sieve=config.name)
