from __future__ import annotations

import asyncio
import dataclasses
import inspect
import re
import signal
import sys
from asyncio import AbstractEventLoop
from contextlib import contextmanager
from datetime import timedelta
from functools import cache, wraps
from types import MappingProxyType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    NoReturn,
    ParamSpec,
    Sequence,
    SupportsIndex,
    TypeGuard,
    TypeVar,
    cast,
    get_type_hints,
    overload,
)

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConstrainedStr, parse_obj_as
from typing_extensions import Self

if TYPE_CHECKING:
    from _typeshed import SupportsKeysAndGetItem, SupportsRichComparison

_T = TypeVar("_T")


def strify(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


_P = ParamSpec("_P")


def syncify(function: Callable[_P, Awaitable[_T]]) -> Callable[_P, _T]:
    @wraps(function)
    def wrapper(*args: list[Any], **kwargs: dict[str, Any]) -> Any:
        return setup_event_loop().run_until_complete(function(*args, **kwargs))  # type: ignore

    return cast(Callable[_P, _T], wrapper)


def unwrap(value: _T | None) -> _T:
    assert value is not None
    return value


class UnreachableException(Exception):
    def __init__(self) -> None:
        self.message = "Unexpected code was reached. This is a bug."


def unreachable() -> NoReturn:
    raise UnreachableException()


def snakecase(text: str) -> str:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").lower()


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
        return parse_obj_as(timedelta, value)
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


def issubtype(subtype: Any, base: type | UnionType) -> bool:
    try:
        if subtype is base:
            return True
        if isinstance(subtype, type) and isinstance(base, type):
            return issubclass(subtype, base)
        if isinstance(base, UnionType):
            for arg in base.__args__:
                if issubtype(subtype, arg):
                    return True
    except Exception:
        pass

    return False


@overload
def loose_isinstance(instance: object, type: type[_T]) -> TypeGuard[_T]:
    ...


@overload
def loose_isinstance(instance: object, type: UnionType) -> bool:
    ...


def loose_isinstance(
    instance: object,
    type: type[_T] | UnionType,
) -> TypeGuard[_T] | bool:
    try:
        return isinstance(instance, type)
    except Exception:
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


_KeyT = TypeVar("_KeyT", covariant=True)
_ValueT = TypeVar("_ValueT", covariant=True)

_NewKeyT = TypeVar("_NewKeyT")
_NewValueT = TypeVar("_NewValueT")


class frozendict(dict[_KeyT, _ValueT]):  # type: ignore
    def __repr__(self) -> str:
        name = type(self).__name__
        if len(self) == 0:
            return f"{name}()"

        return f"{name}({super().__repr__()})"

    def __hash__(self) -> int:  # type: ignore
        return hash(frozenset(self.keys())) ^ hash(frozenset(self.values()))

    def __copy__(self) -> Self:
        return self.copy()

    def __reduce__(self) -> tuple[type[Self], tuple[dict[_KeyT, _ValueT]]]:
        return (type(self), (dict(self),))

    @overload  # type: ignore
    def __or__(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    @overload
    def __or__(
        self: frozendict[_KeyT, _ValueT],
        __value: Iterable[tuple[_NewKeyT, _NewValueT]],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    def __or__(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT]
        | Iterable[tuple[_NewKeyT, _NewValueT]],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        return self.update(__value)

    @overload
    def __ror__(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    @overload
    def __ror__(
        self: frozendict[_KeyT, _ValueT],
        __value: Iterable[tuple[_NewKeyT, _NewValueT]],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    def __ror__(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT]
        | Iterable[tuple[_NewKeyT, _NewValueT]],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        return self.__or__(__value)  # type: ignore

    @overload
    def __ior__(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    @overload
    def __ior__(
        self: frozendict[_KeyT, _ValueT], __value: Iterable[tuple[_NewKeyT, _NewValueT]]
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    def __ior__(  # type: ignore
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT]
        | Iterable[tuple[_NewKeyT, _NewValueT]],
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        return self.__or__(__value)  # type: ignore

    def __copy_if_unreferenced(self) -> Self:
        if sys.getrefcount(self) <= 5:
            return self

        return self.copy()

    def copy(self) -> Self:
        return type(self)(self)

    @overload  # type: ignore
    @classmethod
    def fromkeys(
        cls: type[frozendict[_KeyT, None]],
        __iterable: Iterable[_KeyT],
        __value: None = None,
    ) -> frozendict[_KeyT, None]:
        ...

    @overload
    @classmethod
    def fromkeys(
        cls,
        __iterable: Iterable[_NewKeyT],
        __value: _NewValueT,
    ) -> frozendict[_NewKeyT, _NewValueT]:
        ...

    @classmethod
    def fromkeys(  # type: ignore
        cls,
        __iterable: Iterable[_NewKeyT],
        __value: _NewValueT | None = None,
    ) -> frozendict[_NewKeyT, _NewValueT] | frozendict[_NewKeyT, None]:
        return cls(dict.fromkeys(__iterable, __value))  # type: ignore

    def set(
        self: frozendict[_KeyT, _ValueT],
        __key: _NewKeyT,
        __value: _NewValueT,
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        result = self.__copy_if_unreferenced()
        dict.__setitem__(result, __key, __value)  # type: ignore
        return result

    def setdefault(  # type: ignore
        self: frozendict[_KeyT, _ValueT],
        __key: _NewKeyT,
        __default: _NewValueT,
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        if __key in self:
            return self

        return self.set(__key, __default)

    @overload  # type: ignore
    def update(
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT],
        **kwargs: _NewValueT,
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    @overload
    def update(
        self: frozendict[_KeyT, _ValueT],
        __value: Iterable[tuple[_NewKeyT, _NewValueT]],
        **kwargs: _NewValueT,
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
        ...

    @overload
    def update(
        self: frozendict[_KeyT, _ValueT],
        **kwargs: _NewValueT,
    ) -> frozendict[_KeyT, _ValueT | _NewValueT]:
        ...

    def update(  # type: ignore
        self: frozendict[_KeyT, _ValueT],
        __value: SupportsKeysAndGetItem[_NewKeyT, _NewValueT]
        | Iterable[tuple[_NewKeyT, _NewValueT]]
        | None = None,
        **kwargs: _NewValueT,
    ) -> frozendict[_KeyT | _NewKeyT, _ValueT | _NewValueT]:
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

_SortableFrozenListT = TypeVar("_SortableFrozenListT", bound="frozenlist[Any]")


class frozenlist(list[_ValueT]):  # type: ignore
    def __repr__(self) -> str:
        name = type(self).__name__
        if len(self) == 0:
            return f"{name}()"

        return f"{name}({super().__repr__()})"

    def __hash__(self) -> int:  # type: ignore
        return hash(tuple(self))

    def __copy__(self) -> Self:
        return type(self)(self)

    def __reduce__(self) -> tuple[type[frozenlist[_ValueT]], tuple[list[_ValueT]]]:
        return (type(self), (list(self),))

    @overload
    def __getitem__(self, __index: SupportsIndex) -> _ValueT:
        ...

    @overload
    def __getitem__(self, __index: slice) -> Self:
        ...

    def __getitem__(self, __index: SupportsIndex | slice) -> _ValueT | Self:
        if isinstance(__index, slice):
            return frozenlist(super().__getitem__(__index))  # type: ignore

        return super().__getitem__(__index)  # type: ignore

    def __add__(
        self: frozenlist[_ValueT],
        __iterable: Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
        return self.extend(__iterable)

    def __radd__(
        self: frozenlist[_ValueT],
        __iterable: Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
        return self.__add__(__iterable)

    def __iadd__(
        self: frozenlist[_ValueT],
        __iterable: Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
        return self.__add__(__iterable)

    def __mul__(self, __times: SupportsIndex) -> Self:
        return type(self)(super().__mul__(__times))

    def __rmul__(self, __times: SupportsIndex) -> Self:
        return self.__mul__(__times)

    def __imul__(self, __times: SupportsIndex) -> Self:
        return self.__mul__(__times)

    def __copy_if_unreferenced(self) -> Self:
        if sys.getrefcount(self) <= 5:
            return self

        return type(self)(self)

    def append(  # type: ignore
        self: frozenlist[_ValueT],
        __value: _NewValueT,
    ) -> frozenlist[_ValueT | _NewValueT]:
        result = self.__copy_if_unreferenced()
        list.append(result, __value)  # type: ignore
        return result

    def extend(  # type: ignore
        self: frozenlist[_ValueT],
        __iterable: Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
        result = self.__copy_if_unreferenced()
        list.extend(result, __iterable)  # type: ignore
        return result

    def insert(  # type: ignore
        self: frozenlist[_ValueT],
        __index: SupportsIndex,
        __value: _NewValueT,
    ) -> frozenlist[_ValueT | _NewValueT]:
        result = self.__copy_if_unreferenced()
        list.insert(result, __index, __value)  # type: ignore
        return result

    def remove(  # type: ignore
        self: frozenlist[_ValueT],
        __value: _NewValueT,
    ) -> frozenlist[_ValueT | _NewValueT]:
        result = self.__copy_if_unreferenced()
        list.remove(result, __value)  # type: ignore
        return result

    def reverse(self) -> Self:  # type: ignore
        result = self.__copy_if_unreferenced()
        list.reverse(result)
        return result

    @overload  # type: ignore
    def sort(
        self: _SortableFrozenListT,
        *,
        key: None = None,
        reverse: bool = False,
    ) -> _SortableFrozenListT:
        ...

    @overload
    def sort(
        self,
        *,
        key: Callable[[_ValueT], SupportsRichComparison],
        reverse: bool = False,
    ) -> Self:
        ...

    def sort(
        self,
        *,
        key: Callable[[_ValueT], SupportsRichComparison] | None = None,
        reverse: bool = False,
    ) -> Self:
        result = self.__copy_if_unreferenced()
        list.sort(result, key=key, reverse=reverse)
        return result

    @overload
    def set(
        self: frozenlist[_ValueT],
        __index: SupportsIndex,
        __value: _NewValueT,
    ) -> frozenlist[_ValueT | _NewValueT]:
        ...

    @overload
    def set(
        self: frozenlist[_ValueT],
        __index: slice,
        __value: Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
        ...

    def set(  # type: ignore
        self: frozenlist[_ValueT],
        __index: SupportsIndex | slice,
        __value: _NewValueT | Iterable[_NewValueT],
    ) -> frozenlist[_ValueT | _NewValueT]:
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
            raise NotImplementedError(f"method disabled for {strify(type(self))}.")

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


async def sleep_forever() -> None:
    while True:
        await asyncio.sleep(timedelta(hours=1).total_seconds())


def setup_event_loop() -> AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        try:
            from uvloop import EventLoopPolicy  # type: ignore

            if not isinstance(asyncio.get_event_loop_policy(), EventLoopPolicy):
                asyncio.set_event_loop_policy(EventLoopPolicy())
        except Exception:
            pass

        try:
            return asyncio.get_event_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop


def get_bindings(cls: type[Any], attribute: str, type: type[_T]) -> list[_T]:
    output: list[_T] = []

    for _, function in inspect.getmembers(cls):
        if not inspect.isfunction(function):
            continue

        if values := getattr(function, attribute, None):
            if isinstance(values, Iterable):
                for value in values:
                    if isinstance(value, type):
                        output.append(value)

    return output


def add_binding(function: Callable[..., Any], attribute: str, value: _T) -> list[_T]:
    values: Sequence[_T] | None = getattr(function, attribute, None)

    if not isinstance(values, list):
        values = list(values or [])
        setattr(function, attribute, values)

    values.append(value)

    return values


@contextmanager
def temporary_signal_handler(signums: Sequence[int], handler: Callable[..., Any]) -> Iterator[None]:
    originals: dict[int, Any] = {}
    for signum in signums:
        if original := signal.getsignal(signum):
            originals[signum] = original
        signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            signal.signal(signum, original)
