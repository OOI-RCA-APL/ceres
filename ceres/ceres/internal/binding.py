from typing import Any, Callable, Iterable, Protocol, Sequence, TypeVar, runtime_checkable

from ceres.internal.utilities import get_inner_function

_BINDINGS_ATTRIBUTE = "__local_bindings__"


@runtime_checkable
class Binding(Protocol):
    function: str


_BindingT = TypeVar("_BindingT", bound=Binding)


def add_local_binding(function: Callable[..., object], binding: Binding) -> None:
    function = get_inner_function(function)
    bindings: Sequence[Binding] | None = getattr(function, _BINDINGS_ATTRIBUTE, None)

    if not isinstance(bindings, Sequence):
        bindings = []

    if isinstance(bindings, list):
        bindings.append(binding)
    else:
        bindings = [*bindings, binding]

    setattr(function, _BINDINGS_ATTRIBUTE, bindings)


def get_local_bindings(
    function: Callable[..., Any],
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    function = get_inner_function(function)
    output: list[_BindingT] = []

    if values := getattr(function, _BINDINGS_ATTRIBUTE, None):
        if isinstance(values, Iterable):
            for value in values:
                if isinstance(value, binding_cls):
                    output.append(value)

    return tuple(output)


def get_bindings(
    component_cls: type,
    binding_cls: type[_BindingT],
) -> tuple[_BindingT, ...]:
    bindings: dict[str, _BindingT] = {}

    for cls in reversed(component_cls.__mro__):
        for member in vars(cls).values():
            if not callable(member):
                continue

            for binding in get_local_bindings(member, binding_cls):
                bindings[binding.function] = binding

    return tuple(sorted(bindings.values(), key=lambda current: current.function))
