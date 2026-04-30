from collections.abc import Callable, Hashable
from functools import partial
from typing import TYPE_CHECKING, Any, Final, overload, override

from ceres.__internal__.utilities.undefined import Undefined


def class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
) -> ClassProperty[C, V]:
    """Create a ``ClassProperty`` descriptor from a getter function or classmethod.

    Args:
        fget: A callable that accepts the owner class and returns a value, or a classmethod.

    Returns:
        A ``ClassProperty`` descriptor bound to the given getter.
    """
    return ClassProperty(fget)


class ClassProperty[C, V]:
    """A property descriptor that operate on the class itself rather than an instance."""

    def __init__(
        self,
        fget: Callable[[type[C]], V] | classmethod[C, Any, V],
    ) -> None:
        if isinstance(fget, classmethod):
            fget = fget.__func__

        self.__doc__ = fget.__doc__
        self.__name__: str = fget.__name__
        self.fget: Callable[[type[C]], V] = fget

    def __set_name__(self, definer: type[C], name: str, /) -> None:
        self.__name__ = name
        from annotationlib import Format, get_annotations

        # Assigning the class property with an annotation in a dataclass's body will cause the class
        # property to be computed immediately as the dataclass is being built, which is bad and will
        # likely cause errors. Removing the annotation allows specifying a type annotation when
        # using the assignment syntax without it causing issues.
        if name in get_annotations(definer, format=Format.FORWARDREF):
            definer.__annotations__.pop(name, None)

    def __get__(self, obj: C | None, owner: type[C], /) -> V:
        return self.fget(owner)


@overload
def cached_class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
    *,
    key: Callable[[type[C]], Any] | str | CachedClassProperty[Any, Any] | None = None,
    by: Callable[[Any], Any] | None = None,
) -> CachedClassProperty[C, V]: ...


@overload
def cached_class_property[C, V](
    fget: None = None,
    *,
    key: Callable[[type[C]], Any] | str | CachedClassProperty[Any, Any] | None = None,
    by: Callable[[Any], Any] | None = None,
) -> Callable[[Callable[[type[C]], V] | classmethod[C, Any, V]], CachedClassProperty[C, V]]: ...


def cached_class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V] | None = None,
    *,
    key: Callable[[type[C]], Any] | str | CachedClassProperty | None = None,
    by: Callable[[Any], Any] | None = None,
) -> (
    CachedClassProperty[C, V]
    | Callable[[Callable[[type[C]], V] | classmethod[C, Any, V]], CachedClassProperty[C, V]]
):
    """Create a ``CachedClassProperty`` descriptor with optional cache-invalidation key.

    Can be used as a bare decorator or called with keyword arguments to configure caching
    behavior. When a ``key`` is provided, the cached value is recomputed whenever the key
    changes.

    Args:
        fget: A callable that accepts the owner class and returns a value, or a classmethod.
            When ``None``, return a decorator.
        key: A callable, attribute name, or another ``CachedClassProperty`` used to derive a
            cache-invalidation key from the owner class.
        by: An optional transformation applied to the key before comparison, useful for
            comparing by identity or other derived values.

    Returns:
        A ``CachedClassProperty`` descriptor, or a decorator that produces one.
    """
    if isinstance(key, CachedClassProperty):
        if by is None:
            by = key.by

        key = key.key

    def cached_class_property(
        fget: Callable[[type[C]], V] | classmethod[C, Any, V],
    ) -> CachedClassProperty[C, V]:
        return CachedClassProperty(fget, key=key, by=by)

    if fget is None:
        return cached_class_property

    return cached_class_property(fget)


class CachedClassProperty[C, V](ClassProperty[C, V]):
    """A class property that cache its computed value per owner class.

    Optionally invalidate the cache when a key derived from the owner class changes.
    """

    @override
    def __init__(
        self,
        fget: Callable[[type[C]], V] | classmethod[C, Any, V],
        *,
        key: Callable[[type[C]], Any] | str | None = None,
        by: Callable[[Any], Any] | None = None,
    ) -> None:
        if isinstance(fget, classmethod):
            fget = fget.__func__

        from threading import RLock

        lock = RLock()

        cache: dict[type | tuple[type, Hashable], Any] = {}
        cache_keys: dict[type[Any], Any] = {}

        if isinstance(key, str):

            def key_factory(cls: type[C]) -> Any:
                return getattr(cls, key)
        else:
            key_factory: Callable[[type[C]], Any] | None = key

        if key_factory is None:

            def getter(owner: type[C]) -> V:
                try:
                    return cache[owner]
                except KeyError:
                    with lock:
                        return cache.setdefault(owner, fget(owner))

        else:

            def getter(owner: type[C]) -> V:
                if TYPE_CHECKING:
                    assert key_factory is not None

                incoming_key = key_factory(owner)
                previous_key = cache_keys.get(owner, Undefined)
                if by is None:
                    matched = incoming_key == previous_key
                else:
                    matched = by(incoming_key) == by(previous_key)

                if matched:
                    try:
                        return cache[owner]
                    except KeyError:
                        pass

                with lock:
                    value = fget(owner)
                    cache[owner] = value
                    cache_keys[owner] = incoming_key

                return value

        getter.__doc__ = fget.__doc__
        getter.__name__ = fget.__name__

        super().__init__(getter)

        self.cache: Final = cache
        self.cache_keys: Final = cache_keys
        self.key: Final = key
        self.by: Final = by


fields_cached_class_property = partial(
    cached_class_property,
    key="__pydantic_fields__",
    by=id,
)


def get_declared_slots(cls: type) -> list[str]:
    """Collect all ``__slots__`` declared across a class's MRO, preserving definition order.

    Args:
        cls: The class whose slot declarations to collect.

    Returns:
        A deduplicated list of slot names in MRO order.
    """
    slots: dict[str, None] = {}

    for current in reversed(cls.__mro__):
        __slots__ = getattr(current, "__slots__", ())
        if isinstance(__slots__, str):
            __slots__ = (__slots__,)
        for slot in __slots__:
            slots[slot] = None

    return list(slots)
