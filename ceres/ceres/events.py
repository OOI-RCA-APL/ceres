import inspect
from dataclasses import dataclass, field
from datetime import datetime
from functools import cache
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    Sequence,
    TypeVar,
    overload,
)

from pydantic.dataclasses import dataclass as validated_dataclass

from .address import LocalComponentAddress
from .internal.utilities import get_now
from .message import Message


@validated_dataclass(kw_only=True, frozen=True)
class Event:
    kind: str
    address: LocalComponentAddress
    timestamp: datetime = field(default_factory=get_now)


@validated_dataclass(kw_only=True, frozen=True)
class ConnectedEvent(Event):
    kind: Literal["connected"] = "connected"


@validated_dataclass(kw_only=True, frozen=True)
class DisconnectedEvent(Event):
    kind: Literal["disconnected"] = "disconnected"


@validated_dataclass(kw_only=True, frozen=True)
class MessageSentEvent(Event):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


@validated_dataclass(kw_only=True, frozen=True)
class MessageReceivedEvent(Event):
    kind: Literal["message-received"] = "message-received"
    message: Message


EventT = TypeVar("EventT", bound=Event)

EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


@dataclass(kw_only=True, frozen=True)
class EventBinding:
    address: LocalComponentAddress
    cls: type | object
    function: Callable


@overload
def listen(
    source: str,
    cls: type[EventT],
) -> Callable[
    [Callable[[Any, EventT], None | Awaitable[None]]], Callable[[Any, EventT], Awaitable[None]]
]:
    ...


@overload
def listen(
    source: str,
    cls: object,
) -> Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    ...


def listen(
    source: str,
    cls: type[EventT] | object,
) -> Callable[
    [Callable[[Any, EventT], None | Awaitable[None]]], Callable[[Any, EventT], Awaitable[None]]
] | Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    def inner(function: Callable[[Any, Event], None | Awaitable[None]]) -> Any:
        bindings: list[EventBinding] | None = getattr(function, EVENT_BINDINGS_ATTRIBUTE, None)
        if not bindings or not isinstance(bindings, list):
            bindings = []
            setattr(function, EVENT_BINDINGS_ATTRIBUTE, bindings)

        bindings.append(
            EventBinding(
                address=LocalComponentAddress(source),
                cls=cls,
                function=function,
            )
        )

        return function

    return inner


def get_event_bindings(cls: type) -> Sequence[EventBinding]:
    results: list[EventBinding] = []

    for _, function in inspect.getmembers(cls):
        if not inspect.isfunction(function):
            continue

        if bindings := getattr(function, EVENT_BINDINGS_ATTRIBUTE, None):
            results.extend(bindings)

    return tuple(results)


if not TYPE_CHECKING:
    get_event_bindings = cache(get_event_bindings)
