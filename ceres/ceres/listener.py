from typing import Any, Awaitable, Callable, Sequence, TypeVar

from .address import LocalComponentAddress
from .events import Event
from .internal.binding import Binding, add_binding


class ListenerBinding(Binding):
    sources: Sequence[LocalComponentAddress]
    event: type[Event]
    function: str


_EventT = TypeVar("_EventT", bound=Event)
_Void = None | Awaitable[None]


def on(
    event: type[_EventT],
    sources: str | Sequence[str] = "self",
    /,
) -> Callable[[Callable[[Any, _EventT], _Void]], Callable[[Any, _EventT], _Void]]:
    if isinstance(sources, str):
        sources = [sources]

    def inner(function: Callable[[Any, _EventT], _Void]) -> Any:
        add_binding(
            function,
            ListenerBinding(
                sources=[LocalComponentAddress(source) for source in sources],
                event=event,
                function=function.__name__,
            ),
        )

        return function

    return inner
