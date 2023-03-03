from typing import Any, Awaitable, Callable

from ceres.internal.binding import Binding, add_binding
from ceres.internal.utilities import get_member_name


class RoutineBinding(Binding):
    function: str


_Return = Awaitable[None]


def routine(function: Callable[[Any], _Return]) -> Callable[[Any], _Return]:
    add_binding(
        function,
        RoutineBinding(
            function=get_member_name(function),
        ),
    )

    return function
