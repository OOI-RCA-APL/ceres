import inspect
from typing import Any, Callable, Iterable, Sequence, TypeVar

from ..data import ImmutableDataObject

BINDINGS_ATTRIBUTE = "__bindings__"


class Binding(ImmutableDataObject):
    pass


_BindingT = TypeVar("_BindingT", bound=Binding)


def add_binding(function: Callable[..., Any], binding: Binding) -> None:
    bindings: Sequence[Binding] | None = getattr(function, BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = ()

    bindings = (*bindings, binding)
    setattr(function, BINDINGS_ATTRIBUTE, bindings)


def get_bindings(cls: type[Any], type: type[_BindingT]) -> Sequence[_BindingT]:
    output: list[_BindingT] = []

    for _, function in inspect.getmembers(cls):
        if not inspect.isfunction(function):
            continue

        if values := getattr(function, BINDINGS_ATTRIBUTE, None):
            if isinstance(values, Iterable):
                for value in values:
                    if isinstance(value, type):
                        output.append(value)

    return tuple(output)
