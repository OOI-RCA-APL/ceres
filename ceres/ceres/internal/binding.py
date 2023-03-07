from typing import Any, Callable, Iterable, Sequence, TypeVar

from ceres.data import ImmutableDataObject

_BINDINGS_ATTRIBUTE = "__bindings__"


class Binding(ImmutableDataObject):
    function: str


_BindingT = TypeVar("_BindingT", bound=Binding)


def _get_root_function(function: Callable[..., Any]) -> Callable[..., Any]:
    while True:
        __wrapped__ = getattr(function, "__wrapped__", None)
        if __wrapped__ is not None:
            function = __wrapped__
            continue

        __func__ = getattr(function, "__func__", None)
        if __func__ is not None and __func__ is not function:
            function = __func__
            continue

        break

    return function


def add_function_binding(function: Callable[..., object], binding: Binding) -> None:
    function = _get_root_function(function)
    bindings: Sequence[Binding] | None = getattr(function, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(function, _BINDINGS_ATTRIBUTE, bindings)


def get_function_bindings(
    function: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    function = _get_root_function(function)
    output: list[_BindingT] = []

    if values := getattr(function, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_component_bindings(
    component_cls: type,
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    bindings: dict[str, _BindingT] = {}

    for cls in reversed(component_cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_function_bindings(member, binding_cls):
                bindings[binding.function] = binding

    return tuple(sorted(bindings.values(), key=lambda current: current.function))
