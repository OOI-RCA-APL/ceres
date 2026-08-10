"""Derive the particle classes a component declares, for the metadata route."""

import inspect
from collections.abc import Callable
from types import UnionType
from typing import TYPE_CHECKING, Union, get_args, get_origin

from ceres.config import ClassSieveConfig, MethodSieveConfig, SieveConfig
from ceres.particle import Particle, _get_cls_particle_type

if TYPE_CHECKING:
    from ceres.component import Component


def declared_particle_classes(component: Component) -> list[type[Particle]]:
    """Return the particle classes `component` declares, ordered by discriminator.

    The union of sieve return annotations and `__particles__`. Classes without a
    literal `type` discriminator are dropped since a chart cannot filter on them.
    """
    found: dict[str, type[Particle]] = {}

    for candidate in [
        *_sieve_classes(component),
        *type(component).__particles__,
    ]:
        discriminator = _get_cls_particle_type(candidate)
        if discriminator is not None:
            found[discriminator] = candidate

    return [found[name] for name in sorted(found)]


def default_particle_classes(cls: type[Component]) -> tuple[type[Particle], ...]:
    """Return the particle classes named by `cls`'s `@sieve`-decorated method annotations.

    Backs `Component.__particles__`'s cached default, since a class's sieve bindings are
    fixed once the class body finishes executing.
    """
    from ceres.component import get_sieve_bindings

    found: dict[str, type[Particle]] = {}
    for binding in get_sieve_bindings(cls).values():
        function = getattr(cls, binding.method, None)
        if function is None:
            continue

        for particle in _resolve_particle_members(function):
            discriminator = _get_cls_particle_type(particle)
            if discriminator is not None:
                found[discriminator] = particle

    return tuple(found[name] for name in sorted(found))


def _sieve_classes(component: Component) -> list[type[Particle]]:
    """The particle classes named by the component's sieve return annotations.

    An annotation that fails to resolve is skipped so one bad import cannot hide
    the component's other declarations.
    """
    classes: list[type[Particle]] = []
    for config in component.system.sieves.all():
        function = _sieve_config_function(component, config)
        if function is not None:
            classes.extend(_resolve_particle_members(function))

    return classes


def _sieve_config_function(
    component: Component, config: SieveConfig
) -> Callable[..., object] | None:
    """Return the callable whose return annotation names the particles `config` parses.

    A method sieve reads the bound method named on the component. A class sieve reads
    `process`, which only carries a concrete particle type when the subclass overrides it.
    """
    if isinstance(config, MethodSieveConfig):
        return getattr(component, config.method, None)

    if isinstance(config, ClassSieveConfig):
        return getattr(config.cls, "process", None)

    return None


def _resolve_particle_members(function: Callable[..., object]) -> list[type[Particle]]:
    """Resolve the particle classes named by `function`'s return annotation.

    An annotation that fails to resolve is skipped so one bad import cannot hide the
    caller's other declarations.
    """
    try:
        annotations = inspect.get_annotations(function, eval_str=True)
    except Exception:
        return []

    return _particle_members(annotations.get("return"))


def _particle_members(annotation: object) -> list[type[Particle]]:
    """Unwrap an iterator annotation to the particle classes it yields."""
    if annotation is None:
        return []

    # `Iterator[T]`, `AsyncIterator[T]`, `Iterable[T]`, and `Generator[T, ...]` all carry
    # the yield type as their first argument.
    arguments = get_args(annotation)
    if arguments:
        annotation = arguments[0]

    if get_origin(annotation) in (Union, UnionType):
        members = get_args(annotation)
    else:
        members = (annotation,)

    return [
        member for member in members if isinstance(member, type) and issubclass(member, Particle)
    ]
