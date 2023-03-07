from typing import Any, Awaitable, Callable

from ceres.data import ImmutableDataObject, Name
from ceres.internal.binding import add_local_binding
from ceres.internal.utilities import get_function_name


class RoutineBinding(ImmutableDataObject):
    function: Name


_Return = Awaitable[None]


def routine(function: Callable[[Any], _Return]) -> Callable[[Any], _Return]:
    add_local_binding(
        function,
        RoutineBinding(
            function=get_function_name(function),
        ),
    )

    return function
