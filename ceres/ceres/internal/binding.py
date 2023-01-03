import inspect
from types import FunctionType
from typing import Callable, Iterable, Sequence, TypeVar, cast

from ..data import ImmutableDataObject

_BINDINGS_ATTRIBUTE = "__bindings__"


class Binding(ImmutableDataObject):
    pass


_BindingT = TypeVar("_BindingT", bound=Binding)


def add_binding(function: Callable[..., object], binding: Binding) -> None:
    while hasattr(function, "__wrapped__"):
        function = function.__wrapped__  # type: ignore

    bindings: Sequence[Binding] | None = getattr(function, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = ()

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(function, _BINDINGS_ATTRIBUTE, bindings)


def get_bindings(component_cls: type, binding_cls: type[_BindingT]) -> Sequence[_BindingT]:
    output: list[_BindingT] = []

    for function in _get_functions(component_cls):
        while hasattr(function, "__wrapped__"):
            function = function.__wrapped__  # type: ignore

        if values := getattr(function, _BINDINGS_ATTRIBUTE, None):
            if isinstance(values, Iterable):
                for value in values:
                    if isinstance(value, binding_cls):
                        output.append(value)

    return tuple(output)


def _get_functions(component_cls: type) -> Sequence[FunctionType]:
    functions: dict[str, FunctionType] = {}

    for cls in reversed(cast(Sequence[type], component_cls.__mro__)):
        for name in vars(cls):
            if name in functions:
                continue

            try:
                if (member := getattr(component_cls, name, None)) is None:
                    continue
            except Exception:
                continue

            if not inspect.isfunction(member):
                continue

            functions[name] = member

    return list(functions.values())
