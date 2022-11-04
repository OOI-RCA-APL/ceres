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

from .address import ComponentAddress, LocalComponentAddress
from .alert import Alert
from .message import Message
from .utilities import utc, vdc


@vdc(frozen=True)
class Event:
    kind: str
    address: ComponentAddress
    timestamp: datetime = field(default_factory=utc)


@vdc(frozen=True)
class ConnectedEvent(Event):
    kind: Literal["connected"] = "connected"


@vdc(frozen=True)
class DisconnectedEvent(Event):
    kind: Literal["disconnected"] = "disconnected"


@vdc(frozen=True)
class MessageSentEvent(Event):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


@vdc(frozen=True)
class MessageReceivedEvent(Event):
    kind: Literal["message-received"] = "message-received"
    message: Message


@vdc(frozen=True)
class AlertEmittedEvent(Event):
    kind: Literal["alert-emitted"] = "alert-emitted"
    alert: Alert


EventT = TypeVar("EventT", bound=Event)

_EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


@dataclass(kw_only=True, frozen=True)
class EventBinding:
    address: LocalComponentAddress
    cls: type | object
    function: Callable[..., Any]


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
        bindings: Sequence[EventBinding] | None = getattr(function, _EVENT_BINDINGS_ATTRIBUTE, None)
        if not isinstance(bindings, list):
            bindings = list(bindings or [])
            setattr(function, _EVENT_BINDINGS_ATTRIBUTE, bindings)

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

        if bindings := getattr(function, _EVENT_BINDINGS_ATTRIBUTE, None):
            results.extend(bindings)

    return tuple(results)


if not TYPE_CHECKING:
    get_event_bindings = cache(get_event_bindings)
