from __future__ import annotations

import asyncio
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from typing import Awaitable, Callable, override

from ceres._internal import util
from ceres._internal.lazy import lazy_imports
from ceres._internal.manager.manager import BaseBoundManager
from ceres.address import Address
from ceres.event import ParticleEvent

with lazy_imports(__name__):
    from ceres.component import ComponentSystem, ListenerBinding
    from ceres.config import LoggingConfig
    from ceres.event import AlertEvent, Event, LogEvent, MessageEvent
    from ceres.node import Node
    from ceres.stream import Stream, WriteStream


class EventManager(BaseBoundManager[Event]):
    __slots__ = (
        "_stream",
        "_listeners",
    )

    def __init__(self, source: Node, /) -> None:
        super().__init__(source, Event)
        self._stream: WriteStream[Event] = WriteStream()
        self._listeners = (
            []
            if self._system is None
            else [
                _Listener(system=self._system, binding=binding)
                for binding in self._system.get_listener_bindings()
            ]
        )

    @property
    def settled(self) -> bool:
        return all(listener.settled for listener in self._listeners)

    @property
    @override
    def _node(self) -> Node:
        node = super()._node
        assert node is not None
        return node

    @property
    def _system(self) -> ComponentSystem | None:
        if isinstance(self._node, ComponentSystem):
            return self._node

        return None

    async def __run__(self) -> None:
        if not self._listeners:
            await util.sleep_forever()
            return

        await util.concurrently(listener.__run__() for listener in self._listeners)

    async def settle(self) -> None:
        while not self.settled:
            await util.concurrently(listener.settle() for listener in self._listeners)

    def follow(self) -> Stream[Event]:
        return self._stream.view()

    def emit[**P, T: Event](
        self,
        event_cls: Callable[P, T],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """
        Construct and `propagate` an event, assigning the address of the event to this node's
        address if unset.
        """
        if "address" not in kwargs:
            kwargs["address"] = self._node.address

        event = event_cls(*args, **kwargs)

        self.propagate(event, logging=self._node.get_resolved_logging_config())
        return event

    def propagate(self, event: Event, *, logging: LoggingConfig | None = None) -> None:
        """
        Propagate an event to all systems in the tree, any systems holding a direct or indirect
        reference to a system in the tree, and the containing engine.
        """
        if logging is not None:
            if logging.log_events and not isinstance(event, LogEvent):
                self._node.log.event(logging.log_events_level, event)
            if logging.log_messages and isinstance(event, MessageEvent):
                self._node.log.message(logging.log_messages_level, event.message)
            elif logging.log_particles and isinstance(event, ParticleEvent):
                self._node.log.particle(logging.log_particles_level, event.particle)
            elif logging.log_alerts and isinstance(event, AlertEvent):
                self._node.log.alert(logging.log_alerts_level or event.alert.level, event.alert)

        # Add the event to the outgoing event stream.
        self._stream.put(event)

        container = self._node.__container__

        # If there is a containing node, defer propagation to it.
        if container is not None:
            container.events.propagate(event)
            return

        seen: set[Node] = set()
        seen.add(self._node)

        # Handle the event ourselves.
        self.handle(event)

        # Traverse the tree, calling `handle(event)` for every component.
        for component in self._node.get_components(inclusive=False):
            if component.system not in seen:
                seen.add(component.system)
                component.system.events.handle(event)

            for referencer in component.system.get_referencing_components():
                if referencer.system not in seen:
                    seen.add(referencer.system)
                    referencer.system.events.handle(event)

    def listening(self, event_cls: type[Event], address: Address) -> bool:
        for listener in self._listeners:
            if listener.handles(event_cls, address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        if not self.would_handle(event):
            return False

        handled = False
        for listener in self._listeners:
            if listener.handle(event):
                handled = True

        return handled

    def would_handle(self, event: Event) -> bool:
        # If the node is not running, the event is not handled.
        if not self._node.running:
            return False

        # If the node is stopping, only handle events from nodes it contains.
        if self._node.stopping:
            if not self._node.address.contains(event.address):
                return False

        return self.listening(type(event), event.address)


_ComponentEventHandler = (
    Callable[[Event], None | Awaitable[None]] | Callable[[], None | Awaitable[None]]
)


class _Listener:
    __slots__ = (
        "_system",
        "_binding",
        "_handler",
        "_handler_arity",
        "_queue",
        "_running",
    )

    def __init__(
        self,
        *,
        system: ComponentSystem,
        binding: ListenerBinding,
    ) -> None:
        self._system = system
        self._binding = binding
        self._handler: _ComponentEventHandler = getattr(system.component, binding.method)
        self._handler_arity = len(inspect.signature(self._handler).parameters)
        self._queue: AsyncQueue[Event] = AsyncQueue()
        self._running = False

    @property
    def settled(self) -> bool:
        return self._queue._finished.is_set()  # type: ignore

    def would_handle(self, event: Event) -> bool:
        return self.handles(type(event), event.address)

    async def __run__(self) -> None:
        self._running = True
        try:
            while True:
                event = await self._queue.get()
                await self._process(event)
        finally:
            self._running = False

    async def settle(self) -> None:
        if self._queue.empty():
            return

        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            await self._process(event)

    def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    def handles(self, event_cls: type[Event], address: Address) -> bool:
        if not util.lenient_issubclass(event_cls, self._binding.event):
            return False

        if self._binding.local:
            if address == self._system.address:
                return True

        if self._binding.reference:
            for alias in self._binding.reference:
                if any(
                    component.system.address == address
                    for component in self._system.get_referenced_components(alias)
                ):
                    return True

        if self._binding.address is not None:
            if self._binding.address.matches(address, self._system.address):
                return True

        return False

    def handle(self, event: Event) -> bool:
        if not self.would_handle(event):
            return False

        self._queue.put_nowait(event)
        return True

    async def _process(self, event: Event) -> None:
        try:
            result = self._handler(*[event][: self._handler_arity])
            if inspect.iscoroutine(result):
                await result
        except Exception:
            self._system.log.error(
                f"An exception occurred while processing event {event}: "
                f"{traceback.format_exc()}"
            )
        finally:
            self._queue.task_done()
