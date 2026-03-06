import operator
from collections.abc import Callable, Iterator, MutableMapping, ValuesView
from typing import Any, cast, overload, override

from ceres.__internal__.utilities.undefined import Undefined


@overload
def cached[T: Callable[..., Any]](
    function: None = None,
    /,
    storage: MutableMapping[Any, Any] | None = None,
    weak: bool = False,
) -> Callable[[T], T]: ...


@overload
def cached[T: Callable[..., Any]](function: T, /) -> T: ...


def cached[T: Callable[..., Any]](
    function: T | None = None,
    /,
    storage: MutableMapping[Any, Any] | None = None,
    weak: bool = False,
) -> T | Callable[[T], T]:
    if weak:
        if storage is not None:
            raise ValueError("Cannot use custom storage with weak-key caching.")

        from weakref import WeakKeyDictionary

        storage = WeakKeyDictionary()
    elif storage is None:
        storage = {}

    import inspect
    from annotationlib import Format
    from functools import wraps
    from threading import RLock

    lock = RLock()

    def cached(function: T) -> T:
        parameters = inspect.signature(function, annotation_format=Format.FORWARDREF).parameters
        if len(parameters) == 0:
            value: Any = Undefined

            def wrapper():
                nonlocal value
                if value is Undefined:
                    with lock:
                        value = function()

                return value

            return cast("T", wrapper)

        if len(parameters) == 1 and list(parameters.values())[0].kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):

            def wrapper(arg: Any):
                cached = storage.get(arg, Undefined)
                if cached is not Undefined:
                    return cached

                with lock:
                    return storage.setdefault(arg, function(arg))
        else:

            def wrapper(*args, **kwargs):
                key = (
                    args,
                    None
                    if not kwargs
                    else tuple((key, value) for key, value in sorted(kwargs.items())),
                )
                cached = storage.get(key, Undefined)
                if cached is not Undefined:
                    return cached

                with lock:
                    return storage.setdefault(key, function(*args, **kwargs))

        return cast("T", wraps(function)(wrapper))

    if function is None:
        return cached

    return cached(function)


class LRUCache[K, V](MutableMapping[K, V]):
    __slots__ = (
        "capacity",
        "threshold",
        "_data",
        "_counter",
        "_mutex",
    )

    capacity: int
    threshold: float

    def __init__(self, capacity: int = 100, threshold: float = 0.5):
        import threading

        self.capacity = capacity
        self.threshold = threshold
        self._counter = 0
        self._mutex = threading.Lock()
        self._data: dict[K, tuple[K, V, list[int]]] = {}

    def _inc_counter(self):
        self._counter += 1
        return self._counter

    @overload
    def get(self, key: K) -> V | None: ...
    @overload
    def get[T](self, key: K, default: V | T) -> V | T: ...
    @override
    def get[T](self, key: K, default: V | T | None = None) -> V | T | None:
        item = self._data.get(key)
        if item is not None:
            item[2][0] = self._inc_counter()
            return item[1]
        else:
            return default

    @override
    def __getitem__(self, key: K) -> V:
        item = self._data[key]
        item[2][0] = self._inc_counter()
        return item[1]

    @override
    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    @override
    def __len__(self) -> int:
        return len(self._data)

    @override
    def values(self) -> ValuesView[V]:
        return ValuesView({k: i[1] for k, i in self._data.items()})

    @override
    def __setitem__(self, key: K, value: V, /) -> None:
        self._data[key] = (key, value, [self._inc_counter()])
        self._manage_size()

    @override
    def __delitem__(self, key: K, /) -> None:
        del self._data[key]

    @property
    def size_threshold(self) -> float:
        return self.capacity + self.capacity * self.threshold

    def _manage_size(self) -> None:
        if not self._mutex.acquire(False):
            return
        try:
            while len(self) > self.capacity + self.capacity * self.threshold:
                by_counter = sorted(
                    self._data.values(),
                    key=operator.itemgetter(2),
                    reverse=True,
                )
                for item in by_counter[self.capacity :]:
                    try:
                        del self._data[item[0]]
                    except KeyError:
                        continue
        finally:
            self._mutex.release()
