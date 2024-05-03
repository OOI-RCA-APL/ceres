import asyncio
import inspect
import traceback
from asyncio import Queue as AsyncQueue
from typing import TYPE_CHECKING, Awaitable, Callable, TypeVar

from typing_extensions import ParamSpec, override

from ceres._internal.manager.manager import BaseBoundManager
from ceres._internal.typedecs import __ComponentSystem__, __Node__
from ceres._internal.utilities import lenient_issubclass, sleep_forever
from ceres.address import Address
from ceres.event import Event, LogEvent
from ceres.stream import Stream, WriteStream

_EventT = TypeVar("_EventT", bound=Event)
_EventP = ParamSpec("_EventP")


class EventManager(BaseBoundManager[Event]):
    __slots__ = ("_stream", "_listeners")

    def __init__(
        self,
        source: __Node__,
    ) -> None:
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
    def _node(self) -> __Node__:
        node = super()._node
        assert node is not None
        return node

    @property
    def _system(self) -> __ComponentSystem__ | None:
        from ceres.component import ComponentSystem

        if isinstance(self._node, ComponentSystem):
            return self._node

        return None

    async def process(self) -> None:
        await asyncio.gather(
            *(listener.process() for listener in self._listeners),
            sleep_forever(),
        )

    async def settle(self) -> None:
        while not self.settled:
            await asyncio.gather(*(listener.settle() for listener in self._listeners))

    def follow(self) -> Stream[Event]:
        return self._stream.view()

    def emit(
        self,
        event_cls: Callable[_EventP, _EventT],
        /,
        *args: _EventP.args,
        **kwargs: _EventP.kwargs,
    ) -> _EventT:
        """
        Construct and `propagate` an event, assigning the address of the event to this node's
        address if unset.
        """
        if "address" not in kwargs:
            kwargs["address"] = self._node.address

        event = event_cls(*args, **kwargs)
        logging = self._node.get_resolved_logging_config()
        if logging.log_events and not isinstance(event, LogEvent):
            self._node.log.info(
                "[event] [{type}] {event}",
                type=event.type,
                event=event.model_dump_json(exclude={"id", "timestamp", "address", "type"}),
            )

        self.propagate(event)
        return event

    def propagate(self, event: Event) -> None:
        """
        Propagate an event to all systems in the tree, any systems holding a direct or indirect
        reference to a system in the tree, and the containing engine.
        """
        from ceres.node import Node

        # Add the event to the outgoing event stream.
        self._stream.put(event)

        container = self._node.__container__

        # If there is a parent node, defer propagation to it.
        if container is not None:
            container.events.propagate(event)
            return

        seen: set[Node] = set()
        seen.add(self._node)

        # Handle the event ourselves.
        self.handle(event)

        # Traverse the tree calling `handle(event)` for every subsystem.
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


if TYPE_CHECKING:
    from ceres.component import ListenerBinding as __ListenerBinding__
else:
    __ListenerBinding__ = object

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
        "_processing",
    )

    def __init__(
        self,
        *,
        system: __ComponentSystem__,
        binding: __ListenerBinding__,
    ) -> None:
        self._system = system
        self._binding = binding
        self._handler: _ComponentEventHandler = getattr(system.component, binding.method)
        self._handler_arity = len(inspect.signature(self._handler).parameters)
        self._queue: AsyncQueue[Event] = AsyncQueue()
        self._processing = False

    @property
    def settled(self) -> bool:
        return self._queue._finished.is_set()  # type: ignore

    def would_handle(self, event: Event) -> bool:
        return self.handles(type(event), event.address)

    async def _process_one(self, event: Event) -> None:

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

    async def process(self) -> None:
        self._processing = True
        try:
            while True:
                event = await self._queue.get()
                await self._process_one(event)
        finally:
            self._processing = False

    async def settle(self) -> None:
        if self._queue.empty():
            return

        while True:
            try:
                event = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            await self._process_one(event)

    def clear(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()

    def handles(self, event_cls: type[Event], address: Address) -> bool:
        if not lenient_issubclass(event_cls, self._binding.event):
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
