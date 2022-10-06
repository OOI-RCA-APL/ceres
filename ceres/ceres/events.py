from __future__ import annotations

import inspect
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, TypeVar, overload

from pydantic import BaseModel

from .message import Message
from .path import LocalComponentPath

ConnectionEventKind = Literal["connected", "disconnected", "message-sent", "message-received"]
EventKind = ConnectionEventKind


class BaseEvent(BaseModel):
    kind: EventKind
    path: LocalComponentPath


class ConnectedEvent(BaseEvent):
    kind: ConnectionEventKind = "connected"
    timestamp: datetime


class DisconnectedEvent(BaseEvent):
    kind: ConnectionEventKind = "disconnected"
    timestamp: datetime


class MessageSentEvent(BaseEvent):
    kind: ConnectionEventKind = "message-sent"
    message: Message


class MessageReceivedEvent(BaseEvent):
    kind: ConnectionEventKind = "message-received"
    message: Message


ConnectionEvent = ConnectedEvent | DisconnectedEvent | MessageSentEvent | MessageReceivedEvent

Event = ConnectionEvent

if TYPE_CHECKING:
    from .connection import ConnectionReference

    ListenSource = ConnectionReference

EventT = TypeVar("EventT", bound=Event)

EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


class EventBinding(BaseModel):
    class Config:
        arbitrary_types_allowed = True

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


def get_event_bindings(obj: object) -> list[EventBinding]:
    results: list[EventBinding] = []

    for _, function in inspect.getmembers(type(obj)):
        if not inspect.isfunction(function):
            continue

        if bindings := getattr(function, EVENT_BINDINGS_ATTRIBUTE, None):
            results.extend(bindings)

    return results
