import inspect
from typing import Callable, Iterable, Sequence, TypeVar

from ..data import ImmutableDataObject

BINDINGS_ATTRIBUTE = "__bindings__"


class Binding(ImmutableDataObject):
    pass


_BindingT = TypeVar("_BindingT", bound=Binding)


def add_binding(function: Callable[..., object], binding: Binding) -> None:
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__  # type: ignore

    bindings: Sequence[Binding] | None = getattr(function, BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = ()

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(function, BINDINGS_ATTRIBUTE, bindings)


def get_bindings(component_cls: type, binding_cls: type[_BindingT]) -> Sequence[_BindingT]:
    output: list[_BindingT] = []

    functions = [member for member in vars(component_cls).values() if inspect.isfunction(member)]

    for function in functions:
        while hasattr(function, "__wrapped__"):
            function = function.__wrapped__  # type: ignore

        if values := getattr(function, BINDINGS_ATTRIBUTE, None):
            if isinstance(values, Iterable):
                for value in values:
                    if isinstance(value, binding_cls):
                        output.append(value)

    return tuple(output)
