from __future__ import annotations

import inspect
from dataclasses import dataclass
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

from .message import Message
from .path import LocalComponentPath

ConnectionEventKind = Literal[
    "none", "connected", "disconnected", "message-sent", "message-received"
]
EventKind = ConnectionEventKind


@dataclass(kw_only=True, frozen=True)
class BaseEvent:
    kind: EventKind = "none"
    path: LocalComponentPath


@dataclass(kw_only=True, frozen=True)
class ConnectedEvent(BaseEvent):
    kind: Literal["connected"] = "connected"
    timestamp: datetime


@dataclass(kw_only=True, frozen=True)
class DisconnectedEvent(BaseEvent):
    kind: Literal["disconnected"] = "disconnected"
    timestamp: datetime


@dataclass(kw_only=True, frozen=True)
class MessageSentEvent(BaseEvent):
    kind: Literal["message-sent"] = "message-sent"
    message: Message


@dataclass(kw_only=True, frozen=True)
class MessageReceivedEvent(BaseEvent):
    kind: Literal["message-received"] = "message-received"
    message: Message


ConnectionEvent = ConnectedEvent | DisconnectedEvent | MessageSentEvent | MessageReceivedEvent

Event = ConnectionEvent

if TYPE_CHECKING:
    from .connection import ConnectionReference

    ListenSource = ConnectionReference

EventT = TypeVar("EventT", bound=BaseEvent)

EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


@dataclass(kw_only=True, frozen=True)
class EventBinding:
    path: LocalComponentPath
    cls: type | object
    method: str


@overload
def listen(
    source: ListenSource,
    cls: type[EventT],
) -> Callable[
    [Callable[[Any, EventT], None | Awaitable[None]]], Callable[[Any, EventT], Awaitable[None]]
]:
    ...


@overload
def listen(
    source: ListenSource,
    cls: object,
) -> Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    ...


def listen(
    source: ListenSource,
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
                path=source.path,
                cls=cls,
                method=function.__name__,
            )
        )

        return function

    return inner


@cache
def get_event_bindings(cls: type) -> Sequence[EventBinding]:
    results: list[EventBinding] = []

    for _, function in inspect.getmembers(cls):
        if not inspect.isfunction(function):
            continue

        if bindings := getattr(function, EVENT_BINDINGS_ATTRIBUTE, None):
            results.extend(bindings)

    return tuple(results)
