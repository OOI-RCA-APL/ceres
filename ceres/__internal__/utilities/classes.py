from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any, Final, overload, override

from ceres.__internal__.utilities.undefined import Undefined


def class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
) -> ClassProperty[C, V]:
    return ClassProperty(fget)


@overload
def cached_class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
    *,
    key: Callable[[type[C]], Any] | str | None = None,
) -> ClassProperty[C, V]: ...


@overload
def cached_class_property[C, V](
    fget: None = None,
    *,
    key: Callable[[type[C]], Any] | str | None = None,
) -> Callable[[Callable[[type[C]], V] | classmethod[C, Any, V]], ClassProperty[C, V]]: ...


def cached_class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V] | None = None,
    *,
    key: Callable[[type[C]], Any] | str | None = None,
) -> (
    ClassProperty[C, V]
    | Callable[[Callable[[type[C]], V] | classmethod[C, Any, V]], ClassProperty[C, V]]
):
    def cached_class_property(
        fget: Callable[[type[C]], V] | classmethod[C, Any, V],
    ) -> ClassProperty[C, V]:
        return CachedClassProperty(fget, key=key)

    if fget is None:
        return cached_class_property

    return cached_class_property(fget)


class ClassProperty[C, V]:
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


class CachedClassProperty[C, V](ClassProperty[C, V]):
    @override
    def __init__(
        self,
        fget: Callable[[type[C]], V] | classmethod[C, Any, V],
        *,
        key: Callable[[type[C]], Any] | str | None = None,
    ) -> None:
        if isinstance(fget, classmethod):
            fget = fget.__func__

        from threading import RLock

        cache: dict[type | tuple[type, Hashable], Any] = {}
        cache_keys: dict[type[Any], Any] = {}
        lock = RLock()

        if isinstance(key, str):

            def key_factory(cls: type[C]) -> Any:
                return getattr(cls, key)
        else:
            key_factory: Callable[[type[C]], Any] | None = key

        if key_factory is not None:

            def getter(owner: type[C]) -> V:
                if TYPE_CHECKING:
                    assert key_factory is not None

                key = key_factory(owner)
                previous = cache_keys.get(owner, Undefined)
                if key == previous:
                    try:
                        return cache[owner]
                    except KeyError:
                        pass

                with lock:
                    value = fget(owner)  # type: ignore
                    cache_keys[owner] = key
                    cache[owner] = value

                return value
        else:

            def getter(owner: type[C]) -> V:
                value = cache.get(owner, Undefined)
                if value is Undefined:
                    with lock:
                        value = fget(owner)  # type: ignore
                        value = cache.setdefault(owner, value)

                return value

        getter.__doc__ = fget.__doc__
        getter.__name__ = fget.__name__

        super().__init__(getter)

        self.cache: Final = cache
        self.cache_keys: Final = cache_keys
        self.lock: Final = lock
        self.key: Final = key


def get_declared_slots(cls: type) -> list[str]:
    slots: dict[str, None] = {}

    for current in reversed(cls.__mro__):
        __slots__ = getattr(current, "__slots__", ())
        if isinstance(__slots__, str):
            __slots__ = (__slots__,)
        for slot in __slots__:
            slots[slot] = None

    return list(slots)
