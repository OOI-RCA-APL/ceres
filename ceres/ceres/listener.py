from types import UnionType
from typing import Any, Awaitable, Callable, TypeVar, overload

from .address import LocalComponentAddress
from .events import Event
from .internal.binding import Binding, add_binding


class ListenerBinding(Binding):
    address: LocalComponentAddress
    event: type | UnionType
    function: str


_EventT = TypeVar("_EventT", bound=Event)


@overload
def listen(
    source: str,
    event: type[_EventT],
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
]:
    ...


@overload
def listen(
    source: str,
    event: UnionType,
) -> Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    ...


def listen(
    source: str,
    event: type[_EventT] | UnionType,
) -> Callable[
    [Callable[[Any, _EventT], None | Awaitable[None]]], Callable[[Any, _EventT], Awaitable[None]]
] | Callable[
    [Callable[[Any, Event], None | Awaitable[None]]], Callable[[Any, Event], Awaitable[None]]
]:
    def inner(function: Callable[[Any, Event], None | Awaitable[None]]) -> Any:
        add_binding(
            function,
            ListenerBinding(
                address=LocalComponentAddress(source),
                event=event,
                function=function.__name__,
            ),
        )

        return function

    return inner
