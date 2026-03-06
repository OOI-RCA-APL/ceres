from collections.abc import Callable
from typing import Any, override

from ceres.__internal__.utilities.undefined import Undefined


def class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
) -> ClassProperty[C, V]:
    return ClassProperty(fget)


def cached_class_property[C, V](
    fget: Callable[[type[C]], V] | classmethod[C, Any, V],
) -> ClassProperty[C, V]:
    return CachedClassProperty(fget)


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
    ) -> None:
        super().__init__(fget)

        from threading import RLock

        self._cache: dict[type, Any] = {}
        self._lock = RLock()

    @override
    def __get__(self, obj: C | None, owner: type[C], /) -> V:
        value = self._cache.get(owner, Undefined)
        if value is Undefined:
            with self._lock:
                value = super().__get__(obj, owner)
                value = self._cache.setdefault(owner, value)

        return value


def get_declared_slots(cls: type) -> list[str]:
    slots: dict[str, None] = {}

    for current in reversed(cls.__mro__):
        __slots__ = getattr(current, "__slots__", ())
        if isinstance(__slots__, str):
            __slots__ = (__slots__,)
        for slot in __slots__:
            slots[slot] = None

    return list(slots)
