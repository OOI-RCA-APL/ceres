from typing import Any, Awaitable, Callable, Sequence, TypeVar

from pydantic import validate_arguments

from ceres.data import ImmutableDataObject, Name
from ceres.events import Event
from ceres.internal.binding import add_local_binding
from ceres.internal.utilities import get_function_name


class ListenerBinding(ImmutableDataObject):
    function: Name
    sources: Sequence[Name]
    event_cls: type[Event]


_EventT = TypeVar("_EventT", bound=Event)
_Void = None | Awaitable[None]


@validate_arguments
def on(
    event: type[_EventT],
    sources: Name | Sequence[Name] = "self",
    /,
) -> Callable[[Callable[[Any, _EventT], _Void]], Callable[[Any, _EventT], _Void]]:
    if isinstance(sources, str):
        sources = [sources]

    def bind(function: Callable[[Any, _EventT], _Void]) -> Any:
        add_local_binding(
            function,
            ListenerBinding(
                sources=sources,
                event_cls=event,
                function=get_function_name(function),
            ),
        )

        return function

    return bind
