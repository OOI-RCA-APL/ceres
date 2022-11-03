from __future__ import annotations

import asyncio
import dataclasses
import re
import sys
from datetime import timedelta
from functools import cache, wraps
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Iterable,
    Literal,
    Mapping,
    NoReturn,
    ParamSpec,
    SupportsIndex,
    TypeVar,
    cast,
    get_type_hints,
    overload,
)

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConstrainedStr

from ..utilities import hydrate
from .tasks import ensure_event_loop

if TYPE_CHECKING:
    from _typeshed import SupportsKeysAndGetItem, SupportsRichComparison

T = TypeVar("T")

ParamsT = ParamSpec("ParamsT")


def syncify(function: Callable[ParamsT, Awaitable[T]]) -> Callable[ParamsT, T]:
    @wraps(function)
    def wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:
        ensure_event_loop()
        return asyncio.run(function(*args, **kwargs))  # type: ignore

    return cast(Callable[ParamsT, T], wrapper)


def unwrap(value: T | None) -> T:
    assert value is not None
    return value


class UnreachableException(Exception):
    def __init__(self) -> None:
        self.message = "Unexpected code was reached. This is a bug."


def unreachable() -> NoReturn:
    raise UnreachableException()


def get_type_annotations(obj: object) -> Mapping[str, Any]:
    return MappingProxyType(get_type_hints(obj))


if not TYPE_CHECKING:
    get_type_annotations = cache(get_type_annotations)


def encode_td(value: timedelta) -> str:
    if value < timedelta(milliseconds=1):
        encoded_value, encoded_unit = float(value.microseconds), "us"
    elif value < timedelta(seconds=1):
        encoded_value, encoded_unit = value.microseconds / 1000, "ms"
    elif value < timedelta(minutes=1):
        encoded_value, encoded_unit = value.total_seconds(), "s"
    elif value < timedelta(hours=1):
        encoded_value, encoded_unit = value.total_seconds() / 60, "m"
    elif value < timedelta(days=1):
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60), "h"
    else:
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60 * 24), "d"

    return f"{str(encoded_value).rstrip('0').rstrip('.')}{encoded_unit}"


def show_td(value: timedelta) -> str:
    if value < timedelta(milliseconds=1):
        encoded_value, encoded_unit = float(value.microseconds), "microseconds"
    elif value < timedelta(seconds=1):
        encoded_value, encoded_unit = value.microseconds / 1000, "milliseconds"
    elif value < timedelta(minutes=1):
        encoded_value, encoded_unit = value.total_seconds(), "seconds"
    elif value < timedelta(hours=1):
        encoded_value, encoded_unit = value.total_seconds() / 60, "minutes"
    elif value < timedelta(days=1):
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60), "hours"
    else:
        encoded_value, encoded_unit = value.total_seconds() / (60 * 60 * 24), "days"

    return f"{str(encoded_value).rstrip('0').rstrip('.')} {encoded_unit}"


def decode_td(value: str | timedelta | int | float | Any) -> timedelta:
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    def get_exception() -> ValueError:
        return ValueError(
            "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', 'ms', 's', 'm', 'h' or 'd'."
        )

    if not isinstance(value, str):
        raise get_exception()

    try:
        return hydrate(timedelta, value)
    except Exception:
        pass

    if value.endswith("us"):
        decoded_unit = "us"
    elif value.endswith("ms"):
        decoded_unit = "ms"
    elif value.endswith("s"):
        decoded_unit = "s"
    elif value.endswith("m"):
        decoded_unit = "m"
    elif value.endswith("h"):
        decoded_unit = "h"
    elif value.endswith("d"):
        decoded_unit = "d"
    else:
        raise get_exception()

    try:
        decoded_value = float(value[: -len(decoded_unit)])
    except Exception:
        raise get_exception()

    match decoded_unit:
        case "us":
            return timedelta(microseconds=decoded_value)
        case "ms":
            return timedelta(milliseconds=decoded_value)
        case "s":
            return timedelta(seconds=decoded_value)
        case "m":
            return timedelta(minutes=decoded_value)
        case "h":
            return timedelta(hours=decoded_value)
        case "d":
            return timedelta(days=decoded_value)

    raise get_exception()


if TYPE_CHECKING:
    NameStr = str
    EmailStr = str
    NonEmptyStr = str
else:

    class NameStr(ConstrainedStr):
        regex = re.compile(r"[a-zA-Z\-\_][a-zA-Z0-9\-\_]*")

    class EmailStr(ConstrainedStr):
        regex = re.compile(r".+@.+")

    class NonEmptyStr(ConstrainedStr):
        regex = re.compile(r".+")


def issubtype(value: Any, type_: type | UnionType) -> bool:
    try:
        if value == type_:
            return True
        if isinstance(value, type) and isinstance(type_, type):
            return issubclass(value, type_)
        if isinstance(type_, UnionType):
            for arg in type_.__args__:
                if issubtype(value, arg):
                    return True
    except Exception:
        pass

    return False


def object_has_field(obj: Any, name: str, type: Any = None) -> bool:
    if dataclasses.is_dataclass(obj):
        return any(
            field.name == name and (type is None or issubtype(field.type, type))
            for field in dataclasses.fields(obj)
        )
    if isinstance(obj, BaseModel) or issubclass(obj, BaseModel):
        return any(
            field.name == name and (type is None or issubtype(field.type_, type))
            for field in obj.__fields__.values()
        )

    return False


KeyT = TypeVar("KeyT", covariant=True)
ValueT = TypeVar("ValueT", covariant=True)
FrozenDictT = TypeVar("FrozenDictT", bound="frozendict[Any, Any]")

NewKeyT = TypeVar("NewKeyT")
NewValueT = TypeVar("NewValueT")


class frozendict(dict[KeyT, ValueT]):  # type: ignore
    def __repr__(self) -> str:
        name = type(self).__name__
        if len(self) == 0:
            return f"{name}()"

        return f"{name}({super().__repr__()})"

    def __hash__(self) -> int:  # type: ignore
        return hash(frozenset(self.keys())) ^ hash(frozenset(self.values()))

    def __copy__(self: FrozenDictT) -> FrozenDictT:
        return self.copy()

    def __reduce__(self) -> tuple[type[frozendict[Any, Any]], tuple[dict[KeyT, ValueT]]]:
        return (type(self), (dict(self),))

    @overload  # type: ignore
    def __or__(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    @overload
    def __or__(
        self: frozendict[KeyT, ValueT],
        __value: Iterable[tuple[NewKeyT, NewValueT]],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    def __or__(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT] | Iterable[tuple[NewKeyT, NewValueT]],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        return self.update(__value)

    @overload
    def __ror__(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    @overload
    def __ror__(
        self: frozendict[KeyT, ValueT],
        __value: Iterable[tuple[NewKeyT, NewValueT]],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    def __ror__(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT] | Iterable[tuple[NewKeyT, NewValueT]],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        return self.__or__(__value)  # type: ignore

    @overload
    def __ior__(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    @overload
    def __ior__(
        self: frozendict[KeyT, ValueT], __value: Iterable[tuple[NewKeyT, NewValueT]]
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    def __ior__(  # type: ignore
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT] | Iterable[tuple[NewKeyT, NewValueT]],
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        return self.__or__(__value)  # type: ignore

    def __copy_if_unreferenced(self: FrozenDictT) -> FrozenDictT:
        if sys.getrefcount(self) <= 5:
            return self

        return self.copy()

    def copy(self: FrozenDictT) -> FrozenDictT:
        return type(self)(self)

    @overload  # type: ignore
    @classmethod
    def fromkeys(
        cls: type[frozendict[KeyT, None]],
        __iterable: Iterable[KeyT],
        __value: None = None,
    ) -> frozendict[KeyT, None]:
        ...

    @overload
    @classmethod
    def fromkeys(
        cls,
        __iterable: Iterable[NewKeyT],
        __value: NewValueT,
    ) -> frozendict[NewKeyT, NewValueT]:
        ...

    @classmethod
    def fromkeys(  # type: ignore
        cls,
        __iterable: Iterable[NewKeyT],
        __value: NewValueT | None = None,
    ) -> frozendict[NewKeyT, NewValueT] | frozendict[NewKeyT, None]:
        return cls(dict.fromkeys(__iterable, __value))  # type: ignore

    def set(
        self: frozendict[KeyT, ValueT],
        __key: NewKeyT,
        __value: NewValueT,
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        dict.__setitem__(result, __key, __value)  # type: ignore
        return result

    def setdefault(  # type: ignore
        self: frozendict[KeyT, ValueT],
        __key: NewKeyT,
        __default: NewValueT,
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        if __key in self:
            return self

        return self.set(__key, __default)

    @overload  # type: ignore
    def update(
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT],
        **kwargs: NewValueT,
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    @overload
    def update(
        self: frozendict[KeyT, ValueT],
        __value: Iterable[tuple[NewKeyT, NewValueT]],
        **kwargs: NewValueT,
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        ...

    @overload
    def update(
        self: frozendict[KeyT, ValueT],
        **kwargs: NewValueT,
    ) -> frozendict[KeyT, ValueT | NewValueT]:
        ...

    def update(  # type: ignore
        self: frozendict[KeyT, ValueT],
        __value: SupportsKeysAndGetItem[NewKeyT, NewValueT]
        | Iterable[tuple[NewKeyT, NewValueT]]
        | None = None,
        **kwargs: NewValueT,
    ) -> frozendict[KeyT | NewKeyT, ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()

        if __value is None:
            dict.update(result, **kwargs)  # type: ignore
        else:
            dict.update(result, __value, **kwargs)  # type: ignore

        return result


def __patch_frozendict() -> None:
    """
    Modify frozendict to disable all remaining mutating methods.
    """
    for method in [
        dict.__delitem__,
        dict.__setitem__,
        dict.clear,
        dict.pop,
        dict.popitem,
        # dict.setdefault,
        # dict.update,
    ]:

        @wraps(method)  # type: ignore
        def disabled(self: Any, *args: Any) -> NoReturn:
            raise NotImplementedError(f"method disabled for {type(self)}")

        setattr(frozendict, method.__name__, disabled)


__patch_frozendict()

FrozenListT = TypeVar("FrozenListT", bound="frozenlist[Any]")
SortableFrozenListT = TypeVar("SortableFrozenListT", bound="frozenlist[Any]")


class frozenlist(list[ValueT]):  # type: ignore
    def __repr__(self) -> str:
        name = type(self).__name__
        if len(self) == 0:
            return f"{name}()"

        return f"{name}({super().__repr__()})"

    def __hash__(self) -> int:  # type: ignore
        return hash(tuple(self))

    def __copy__(self: FrozenListT) -> FrozenListT:
        return type(self)(self)

    def __reduce__(self) -> tuple[type[frozenlist[ValueT]], tuple[list[ValueT]]]:
        return (type(self), (list(self),))

    @overload
    def __getitem__(self, __index: SupportsIndex) -> ValueT:
        ...

    @overload
    def __getitem__(self: FrozenListT, __index: slice) -> FrozenListT:
        ...

    def __getitem__(self: FrozenListT, __index: SupportsIndex | slice) -> ValueT | FrozenListT:
        if isinstance(__index, slice):
            return frozenlist(super().__getitem__(__index))  # type: ignore

        return super().__getitem__(__index)  # type: ignore

    def __add__(
        self: frozenlist[ValueT],
        __iterable: Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        return self.extend(__iterable)

    def __radd__(
        self: frozenlist[ValueT],
        __iterable: Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        return self.__add__(__iterable)

    def __iadd__(
        self: frozenlist[ValueT],
        __iterable: Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        return self.__add__(__iterable)

    def __mul__(self: FrozenListT, __times: SupportsIndex) -> FrozenListT:
        return type(self)(super().__mul__(__times))

    def __rmul__(self: FrozenListT, __times: SupportsIndex) -> FrozenListT:
        return self.__mul__(__times)

    def __imul__(self: FrozenListT, __times: SupportsIndex) -> FrozenListT:
        return self.__mul__(__times)

    def __copy_if_unreferenced(self: FrozenListT) -> FrozenListT:
        if sys.getrefcount(self) <= 5:
            return self

        return type(self)(self)

    def append(  # type: ignore
        self: frozenlist[ValueT],
        __value: NewValueT,
    ) -> frozenlist[ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        list.append(result, __value)  # type: ignore
        return result

    def extend(  # type: ignore
        self: frozenlist[ValueT],
        __iterable: Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        list.extend(result, __iterable)  # type: ignore
        return result

    def insert(  # type: ignore
        self: frozenlist[ValueT],
        __index: SupportsIndex,
        __value: NewValueT,
    ) -> frozenlist[ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        list.insert(result, __index, __value)  # type: ignore
        return result

    def remove(  # type: ignore
        self: frozenlist[ValueT],
        __value: NewValueT,
    ) -> frozenlist[ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        list.remove(result, __value)  # type: ignore
        return result

    def reverse(self: FrozenListT) -> FrozenListT:  # type: ignore
        result = self.__copy_if_unreferenced()
        list.reverse(result)
        return result

    @overload  # type: ignore
    def sort(
        self: SortableFrozenListT,
        *,
        key: None = None,
        reverse: bool = False,
    ) -> SortableFrozenListT:
        ...

    @overload
    def sort(
        self: FrozenListT,
        *,
        key: Callable[[ValueT], SupportsRichComparison],
        reverse: bool = False,
    ) -> FrozenListT:
        ...

    def sort(
        self: FrozenListT,
        *,
        key: Callable[[ValueT], SupportsRichComparison] | None = None,
        reverse: bool = False,
    ) -> FrozenListT:
        result = self.__copy_if_unreferenced()
        list.sort(result, key=key, reverse=reverse)
        return result

    @overload
    def set(
        self: frozenlist[ValueT],
        __index: SupportsIndex,
        __value: NewValueT,
    ) -> frozenlist[ValueT | NewValueT]:
        ...

    @overload
    def set(
        self: frozenlist[ValueT],
        __index: slice,
        __value: Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        ...

    def set(  # type: ignore
        self: frozenlist[ValueT],
        __index: SupportsIndex | slice,
        __value: NewValueT | Iterable[NewValueT],
    ) -> frozenlist[ValueT | NewValueT]:
        result = self.__copy_if_unreferenced()
        list.__setitem__(result, __index, __value)  # type: ignore
        return result


def __patch_frozenlist() -> None:
    """
    Modify frozenlist to disable all remaining mutating methods.
    """
    for method in [
        list.__delitem__,
        # list.__iadd__,
        list.__setitem__,
        # list.append,
        list.clear,
        # list.extend,
        # list.insert,
        list.pop,
        # list.remove,
        # list.reverse,
        # list.sort,
    ]:

        @wraps(method)  # type: ignore
        def disabled(self: Any, *args: Any) -> NoReturn:
            raise NotImplementedError(f"method disabled for {type(self)}.")

        setattr(frozenlist, method.__name__, disabled)


__patch_frozenlist()


@overload
def validate_positive_timedelta(value: Any, *, nullable: Literal[False] = ...) -> timedelta:
    ...


@overload
def validate_positive_timedelta(value: Any, *, nullable: Literal[True] = ...) -> timedelta | None:
    ...


def validate_positive_timedelta(value: Any, *, nullable: bool = False) -> timedelta | None:
    if nullable and value is None:
        return None

    if (decoded := decode_td(value)) <= timedelta():
        raise ValueError("must be greater than zero")

    return decoded


def validate_crontab(value: str) -> str:
    try:
        CronTrigger.from_crontab(value)
    except Exception:
        raise ValueError("invalid crontab expression")

    return value
