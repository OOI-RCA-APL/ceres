import inspect
from types import FunctionType
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

    for function in _get_functions(component_cls):
        while hasattr(function, "__wrapped__"):
            function = function.__wrapped__  # type: ignore

        if values := getattr(function, BINDINGS_ATTRIBUTE, None):
            if isinstance(values, Iterable):
                for value in values:
                    if isinstance(value, binding_cls):
                        output.append(value)

    return tuple(output)


def _get_functions(component_cls: type) -> Sequence[FunctionType]:
    functions: list[FunctionType] = []

    for name in dir(component_cls):
        if (member := getattr(component_cls, name, None)) is None:
            continue
        if not inspect.isfunction(member):
            continue
        functions.append(member)

    return functions
