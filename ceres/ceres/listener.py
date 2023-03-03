from typing import Any, Awaitable, Callable, Sequence, TypeVar

from ceres.events import Event
from ceres.internal.binding import Binding, add_binding
from ceres.internal.utilities import get_member_name


class ListenerBinding(Binding):
    sources: Sequence[str]
    event_cls: type[Event]
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
                sources=sources,
                event_cls=event,
                function=get_member_name(function),
            ),
        )

        return function

    return inner
