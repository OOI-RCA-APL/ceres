from __future__ import annotations

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

from .internal.utilities import get_now
from .message import Message
from .path import LocalComponentPath


@validated_dataclass(kw_only=True, frozen=True)
class Event:
    kind: str
    path: LocalComponentPath
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


if TYPE_CHECKING:
    from .component import ComponentInterface
    from .reference import ComponentReference

    ListenSource = ComponentReference[ComponentInterface]

EventT = TypeVar("EventT", bound=Event)

EVENT_BINDINGS_ATTRIBUTE = "__event_bindings__"


@dataclass(kw_only=True, frozen=True)
class EventBinding:
    path: LocalComponentPath
    event_cls: type | object
    function: Callable


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
                event_cls=cls,
                function=function,
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
