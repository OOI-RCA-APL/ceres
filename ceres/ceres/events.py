from __future__ import annotations

import inspect
from datetime import datetime
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Literal, TypeVar

from pydantic import BaseModel

from .message import Message
from .path import LocalComponentPath

ConnectionEventKind = Literal["connected", "disconnected", "message-sent", "message-received"]


class BaseEvent(BaseModel):
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

EventKind = ConnectionEventKind
Event = ConnectionEvent

if TYPE_CHECKING:
    from .connection import UseConnection

    ListenTarget = UseConnection

EventT = TypeVar("EventT", bound=Event)

EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


class EventBinding(BaseModel):
    path: LocalComponentPath
    event: EventKind
    method: str


def listen(
    target: ListenTarget,
    kind: EventKind,
) -> Callable[
    [Callable[[Any, EventT], None | Awaitable[None]]], Callable[[Any, EventT], Awaitable[None]]
]:
    def inner(function: Callable[[Any, EventT], None | Awaitable[None]]) -> Any:
        bindings: list[EventBinding] | None = getattr(function, EVENT_BINDINGS_ATTRIBUTE, None)
        if not bindings or not isinstance(bindings, list):
            bindings = []
            setattr(function, EVENT_BINDINGS_ATTRIBUTE, bindings)

        bindings.append(
            EventBinding(
                path=target.path,
                event=kind,
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
