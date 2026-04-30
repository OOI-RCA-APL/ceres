from collections.abc import Callable, Collection, Hashable, Iterable, Iterator, Sequence, Set
from typing import TYPE_CHECKING, Any, cast, overload, override
from weakref import WeakSet, ref

if TYPE_CHECKING:
    from ceres.__internal__.utilities.typing import Stringy


def uniq[T](
    iterable: Iterable[T],
    /,
    key: Callable[[T], Hashable] | None = None,
) -> Iterable[T]:
    """Yield unique elements from ``iterable``, preserving first-seen order.

    Args:
        iterable: The source of elements to deduplicate.
        key: An optional function that produce a hashable identity for each element. Default to
            using the element's hash or ``id`` for unhashable objects.

    Yields:
        Each element the first time its key is encountered.
    """
    if key is None:
        key = _get_hash_or_id

    seen: set[Hashable] = set()

    for value in iterable:
        identity = key(value)
        if identity in seen:
            continue

        seen.add(identity)
        yield value


def _get_hash_or_id(value: object, /) -> Hashable:
    """Return the hash of ``value`` if it is hashable, otherwise return its ``id``."""
    if isinstance(value, Hashable):
        return hash(value)

    return id(value)


def group_by[K, V](
    iterable: Iterable[V],
    /,
    key: Callable[[V], K],
) -> Iterable[tuple[K, list[V]]]:
    """Group elements of ``iterable`` by a key function.

    Args:
        iterable: The source of elements to group.
        key: A function that derive a grouping key from each element.

    Yields:
        Tuples of ``(key, elements)`` where ``elements`` is the list of values sharing that key.
    """
    from collections import defaultdict

    groups: defaultdict[K, list[V]] = defaultdict(list)
    for value in iterable:
        groups[key(value)].append(value)
    yield from groups.items()


@overload
def seq[T: Stringy](value: T, /) -> Sequence[T]: ...


@overload
def seq[T](value: T | Sequence[T], /) -> Sequence[T]: ...


def seq[T](value: T | Sequence[T], /) -> Sequence[T]:
    """Wrap a single value in a one-element tuple, or return it unchanged if already a sequence.

    Args:
        value: A single value or an existing sequence.

    Returns:
        A sequence containing the value.
    """
    from ceres.__internal__.utilities.typing import is_sequence

    if is_sequence(value):
        return value

    return (value,)


type RecursiveIterable[T] = Iterable[T | RecursiveIterable[T]]
type MaybeRecursiveIterable[T] = T | RecursiveIterable[T]


def flatten[T](value: RecursiveIterable[T], /) -> Iterator[T]:
    """Recursively flatten nested iterables into a single stream of leaf values.

    Args:
        value: A possibly nested iterable of values.

    Yields:
        Each non-iterable leaf element found at any depth.
    """
    from ceres.__internal__.utilities.typing import is_iterable

    for current in value:
        if is_iterable(current):
            yield from flatten(current)
        else:
            yield current


class OrderedSet[T](set[T]):
    """A set that preserve insertion order.

    Iteration, indexing, and pop all follow the order in which elements were added.
    """

    __slots__ = ("_values",)

    _values: list[T]

    @override
    def __init__(self, values: Iterable[T] | None = None, /) -> None:
        if values is not None:
            self._values = list(uniq(values))
            super().update(self._values)
        else:
            self._values = []

    @override
    def copy(self) -> OrderedSet[T]:
        cp = self.__class__()
        cp._values = self._values.copy()
        set.update(cp, cp._values)
        return cp

    @override
    def add(self, element: T) -> None:
        if element not in self:
            self._values.append(element)
        super().add(element)

    @override
    def remove(self, element: T) -> None:
        super().remove(element)
        self._values.remove(element)

    @override
    def pop(self) -> T:
        try:
            value = self._values.pop()
        except IndexError:
            raise KeyError("pop from an empty set") from None
        super().remove(value)
        return value

    def insert(self, pos: int, element: T) -> None:
        """Insert ``element`` at position ``pos`` if it is not already present.

        Args:
            pos: The index at which to insert.
            element: The value to insert.
        """
        if element not in self:
            self._values.insert(pos, element)
        super().add(element)

    @override
    def discard(self, element: T) -> None:
        if element in self:
            self._values.remove(element)
            super().remove(element)

    @override
    def clear(self) -> None:
        super().clear()
        self._values = []

    def __getitem__(self, key: int) -> T:
        return self._values[key]

    @override
    def __iter__(self) -> Iterator[T]:
        return iter(self._values)

    def __add__(self, other: Iterator[T]) -> OrderedSet[T]:
        return self.union(other)

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._values!r})"

    __str__ = __repr__

    @override
    def update(self, *iterables: Iterable[T]) -> None:
        for iterable in iterables:
            for value in iterable:
                if value not in self:
                    self._values.append(value)
                    super().add(value)

    @override
    def __ior__[O](self, other: Set[O]) -> OrderedSet[T | O]:  # type: ignore
        self.update(other)  # type: ignore
        return self  # type: ignore

    @override
    def union[O](self, *other: Iterable[O]) -> OrderedSet[T | O]:
        result: OrderedSet[T | O] = self.copy()  # type: ignore
        result.update(*other)
        return result

    @override
    def __or__[O](self, other: Set[O]) -> OrderedSet[T | O]:
        return self.union(other)

    @override
    def intersection(self, *other: Iterable[Any]) -> OrderedSet[T]:
        other_set: set[Any] = set()
        other_set.update(*other)
        return self.__class__(a for a in self if a in other_set)

    @override
    def __and__(self, other: Set[Any]) -> OrderedSet[T]:
        return self.intersection(other)

    @override
    def symmetric_difference(self, other: Iterable[T]) -> OrderedSet[T]:
        collection: Collection[T]
        if isinstance(other, set):
            collection = other_set = other
        elif isinstance(other, Collection):
            collection = other
            other_set = set(other)
        else:
            collection = list(other)
            other_set = set(collection)
        result = self.__class__(a for a in self if a not in other_set)
        result.update(a for a in collection if a not in self)
        return result

    @override
    def __xor__[O](self, other: Set[O]) -> OrderedSet[T | O]:
        return cast("OrderedSet[T | O]", self).symmetric_difference(other)

    @override
    def difference(self, *other: Iterable[Any]) -> OrderedSet[T]:
        other_set = super().difference(*other)
        return self.__class__(a for a in self._values if a in other_set)

    @override
    def __sub__(self, other: Set[T | None]) -> OrderedSet[T]:
        return self.difference(other)

    @override
    def intersection_update(self, *other: Iterable[Any]) -> None:
        super().intersection_update(*other)
        self._values = [a for a in self._values if a in self]

    @override
    def __iand__(self, other: Set[object]) -> OrderedSet[T]:
        self.intersection_update(other)
        return self

    @override
    def symmetric_difference_update(self, other: Iterable[Any]) -> None:
        collection = other if isinstance(other, Collection) else list(other)
        super().symmetric_difference_update(collection)
        self._values = [a for a in self._values if a in self]
        self._values += [a for a in collection if a in self]

    @override
    def __ixor__[O](self, other: Set[O]) -> OrderedSet[T | O]:  # type: ignore
        self.symmetric_difference_update(other)
        return cast("OrderedSet[T | O]", self)

    @override
    def difference_update(self, *other: Iterable[Any]) -> None:
        super().difference_update(*other)
        self._values = [a for a in self._values if a in self]

    def __isub__(self, other: Set[T | None]) -> OrderedSet[T]:  # type: ignore  # noqa: E501
        self.difference_update(other)
        return self


class OrderedWeakSet[T](WeakSet[T]):
    """A ``WeakSet`` that preserve insertion order using an ``OrderedSet`` as backing storage."""

    def __init__(self, data: Iterable[T] | None = None) -> None:
        super().__init__()
        self.data = OrderedSet() if data is None else OrderedSet(ref(current) for current in data)
