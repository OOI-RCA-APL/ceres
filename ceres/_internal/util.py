from __future__ import annotations

import asyncio
import dataclasses
import os
import platform
import re
import typing
from asyncio import AbstractEventLoop, Future
from collections import defaultdict
from collections.abc import Set
from contextlib import contextmanager
from datetime import timedelta
from enum import Enum
from os import PathLike as _BasePathLike
from pathlib import Path
from threading import Event
from typing import (
    TYPE_CHECKING,
    AbstractSet,
    Any,
    Awaitable,
    Callable,
    ClassVar,
    Collection,
    Coroutine,
    Hashable,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    TypeAlias,
    TypeVar,
    Union,
    cast,
    overload,
    override,
)
from weakref import WeakSet, ref

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model, validate_call
from pydantic.fields import FieldInfo
from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator
from typing_extensions import TypeIs

from ceres._internal.lazy import lazy_imports

with lazy_imports(__name__, export=True):
    from sqlalchemy import SQLColumnExpression

    from ceres.data import MaybeSequence
    from ceres.util import azip_latest as azip_latest
    from ceres.util import cancel as cancel
    from ceres.util import concurrently as concurrently
    from ceres.util import ensure_event_loop as ensure_event_loop
    from ceres.util import wait_all as wait_all
    from ceres.util import wait_any as wait_any


NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"


def strify(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


def reprify(value: object) -> str:
    try:
        return repr(value)
    except Exception:
        return "<__repr__() raised exception>"


def syncify[**P, T](function: Callable[P, Awaitable[T] | T]) -> Callable[P, T]:
    import inspect

    from ceres.util import ensure_event_loop

    if not inspect.iscoroutinefunction(function):
        return cast(Callable[P, T], function)

    from functools import wraps

    @wraps(function)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> Any:
        return ensure_event_loop().run_until_complete(function(*args, **kwargs))

    return cast(Callable[P, T], wrapper)


async def awaitify[T](value: Awaitable[T] | T) -> T:
    import inspect

    if inspect.isawaitable(value):
        return cast(T, await value)

    return cast(T, value)


def dictify(obj: object) -> dict[str, Any]:
    def includes(key: str) -> bool:
        return not key.startswith("__")

    try:
        if is_mapping(obj):
            return dict(obj)
        if is_dataclass_instance(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return {
                key: getattr(obj, key) for key in obj.__class__.model_fields.keys() if includes(key)
            }
        if isinstance(obj, type):
            return {key: getattr(obj, key) for key in dir(obj) if includes(key)}
        slots: tuple[str, ...] | None = getattr(obj, "__slots__", None)
        if slots is not None:
            return {name: getattr(obj, name) for name in slots if includes(name)}
        return {key: value for key, value in obj.__dict__.items() if includes(key)}
    except Exception:
        raise ValueError("object cannot be dictified")


class DataclassLike(Protocol):
    __dataclass_fields__: ClassVar[dict[str, dataclasses.Field[Any]]]
    __dataclass_params__: ClassVar[Any]
    __post_init__: Any


class PydanticDataclassLike(DataclassLike, Protocol):
    __pydantic_config__: ClassVar[ConfigDict]
    __pydantic_complete__: ClassVar[bool]
    __pydantic_core_schema__: ClassVar[CoreSchema]
    __pydantic_decorators__: ClassVar[Any]
    __pydantic_fields__: ClassVar[dict[str, FieldInfo]]
    __pydantic_serializer__: ClassVar[SchemaSerializer]
    __pydantic_validator__: ClassVar[SchemaValidator]

    def __init__(self, *args: Any, **kwargs: Any) -> None: ...


def is_dataclass_instance(obj: object) -> TypeIs[DataclassLike]:
    return not isinstance(obj, type) and is_dataclass(obj)


def is_dataclass_type(obj: object) -> TypeIs[DataclassLike]:
    return isinstance(obj, type) and is_dataclass(obj)


def is_dataclass(obj: object) -> TypeIs[DataclassLike | type[DataclassLike]]:
    return dataclasses.is_dataclass(obj)


def is_pydantic_dataclass_type(obj: object) -> TypeIs[type[PydanticDataclassLike]]:
    return isinstance(obj, type) and is_pydantic_dataclass(obj)


def is_pydantic_dataclass_instance(obj: object) -> TypeIs[PydanticDataclassLike]:
    return not isinstance(obj, type) and is_pydantic_dataclass(obj)


def is_pydantic_dataclass(
    obj: object,
) -> TypeIs[PydanticDataclassLike | type[PydanticDataclassLike]]:
    return dataclasses.is_dataclass(obj) and hasattr(obj, "__pydantic_core_schema__")


ModelLike = BaseModel | PydanticDataclassLike


def snakecase(text: str) -> str:
    import re

    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").lower()


def randstr(characters: str, length: int) -> str:
    import random

    return "".join(random.choice(characters) for _ in range(length))


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

    def get_exception() -> ValueError:
        return ValueError(
            "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
            "'ms', 's', 'm', 'h' or 'd'."
        )

    if isinstance(value, str):
        try:
            return get_type_adapter(timedelta).validate_python(value)
        except Exception:
            pass

        try:
            value = int(value)
            return timedelta(seconds=value)
        except Exception:
            pass

        try:
            value = float(value)
            return timedelta(seconds=value)
        except Exception:
            pass

        value = str(value).strip().lower()

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

    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    raise get_exception()


Stringy: TypeAlias = str | bytes | bytearray | memoryview


def is_stringy(obj: Any) -> TypeIs[Stringy]:
    return isinstance(obj, Stringy)


def is_iterable(obj: Any) -> TypeIs[Iterable[Any]]:
    if not isinstance(obj, Iterable):
        return False

    try:
        iter(obj)
    except Exception:
        return False

    return True


def is_true_iterable(obj: Any) -> TypeIs[Iterable[Any]]:
    return is_iterable(obj) and not is_stringy(obj) and not isinstance(obj, Future)


def is_collection(obj: Any) -> TypeIs[Collection[Any]]:
    if not isinstance(obj, Collection):
        return False

    try:
        len(obj)
        iter(obj)
    except Exception:
        return False

    return True


def is_true_collection(obj: Any) -> TypeIs[Collection[Any]]:
    return is_collection(obj) and not is_stringy(obj)


def is_sequence(obj: Any) -> TypeIs[Sequence[Any]]:
    if not isinstance(obj, Sequence):
        return False

    try:
        len(obj)
        iter(obj)
    except Exception:
        return False

    return True


def is_true_sequence(obj: Any) -> TypeIs[Sequence[Any]]:
    return is_sequence(obj) and not is_stringy(obj)


def is_mapping(obj: Any) -> TypeIs[Mapping[Any, Any]]:
    if not isinstance(obj, Mapping):
        return False

    try:
        obj.keys()
    except Exception:
        return False

    return True


def traverse(
    obj: object,
    visit: Callable[[object], bool | None],
    seen: set[int] | None = None,
) -> None:
    if seen is None:
        seen = set()
    if id(obj) in seen:
        return

    seen.add(id(obj))

    descend = visit(obj)
    if descend is not None:
        if not descend:
            return
    if obj is None:
        return

    if isinstance(obj, BaseModel):
        for name in obj.__class__.model_fields.keys():
            element = getattr(obj, name, None)
            traverse(element, visit, seen)
    elif is_dataclass_instance(obj):
        for field in dataclasses.fields(obj):
            element = getattr(obj, field.name, None)
            traverse(element, visit, seen)
    elif is_mapping(obj):
        for key, value in obj.items():
            traverse(key, visit, seen)
            traverse(value, visit, seen)
    elif is_true_collection(obj):
        for value in obj:
            traverse(value, visit, seen)


if TYPE_CHECKING:
    from builtins import isinstance as lenient_isinstance  # type: ignore
    from builtins import issubclass as lenient_issubclass  # type: ignore
else:

    def lenient_isinstance(obj, cls):
        try:
            return isinstance(obj, cls)
        except TypeError:
            return False

    def lenient_issubclass(obj, cls):
        try:
            return issubclass(obj, cls)
        except TypeError:
            return False


async def sleep_forever() -> None:
    import math

    while True:
        await asyncio.sleep(math.inf)


def get_event_loop_or_none() -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def dbg[T](value: T) -> T:
    import rich

    rich.print(value)
    return value


@overload
def cached[T: Callable[..., Any]](
    function: None = None, *, max_size: int | None = None
) -> Callable[[T], T]: ...


@overload
def cached[T: Callable[..., Any]](function: T) -> T: ...


def cached[T: Callable[..., Any]](
    function: T | None = None,
    *,
    max_size: int | None = None,
) -> T | Callable[[T], T]:
    from functools import lru_cache

    def cached(function: T) -> T:
        return lru_cache(maxsize=max_size)(function)  # type: ignore

    if function is None:
        return cached

    return cached(function)


def get_function_name(function: Callable[..., Any]) -> str:
    original = function.__name__

    if function.__name__.startswith("__") and not function.__name__.endswith("__"):
        tokens = function.__qualname__.split(".")
        if len(tokens) < 2:
            return original

        return f"_{tokens[-2]}{original}"

    return original


def get_inner_function(function: Callable[..., Any]) -> Callable[..., Any]:
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


def get_args_model(
    function: Callable[..., Any],
    *,
    model_name: str | None = None,
    model_module: str | None = None,
    model_config: ConfigDict | None = None,
    model_base: type[BaseModel] | None = None,
    remove_self: bool = True,
    inner: bool = True,
) -> type[BaseModel]:
    import inspect

    function = get_inner_function(function) if inner else function

    if model_name is None:
        model_name = f"{upper_camel(function.__name__)}Args"

    (
        position_parameter_names,
        _,
        kwargs_parameter_name,
        positional_parameter_defaults,
        keyword_only_parameter_names,
        keyword_only_parameter_defaults,
        _,
    ) = inspect.getfullargspec(function)

    annotations = typing.get_type_hints(function, include_extras=True)
    position_parameter_names = position_parameter_names or []
    positional_parameter_defaults = positional_parameter_defaults or ()
    keyword_only_parameter_names = keyword_only_parameter_names or []
    keyword_only_parameter_defaults = keyword_only_parameter_defaults or {}

    if remove_self:
        position_parameter_names = [arg for arg in position_parameter_names if arg != "self"]

    positional_parameter_defaults = (Field(),) * (
        len(position_parameter_names) - len(positional_parameter_defaults)
    ) + positional_parameter_defaults

    positional_parameters = {
        name: (annotations.get(name, Any), default)
        for name, default in zip(position_parameter_names, positional_parameter_defaults)
    }
    keyword_only_parameters = {
        name: (annotations.get(name, Any), keyword_only_parameter_defaults.get(name, Field()))
        for name in keyword_only_parameter_names
    }

    parameters: dict[str, Any] = {**positional_parameters, **keyword_only_parameters}

    # Allow extra arguments if there is a `**kwargs` parameter in the function signature.
    if kwargs_parameter_name and model_base is None:
        model_config = (
            {**(model_config or {}), "extra": "allow"} if kwargs_parameter_name else model_config
        )

    model = create_model(
        model_name,
        __config__=model_config,
        __module__=model_module or "__dynamic__",
        __base__=model_base,
        **parameters,
    )

    model.__doc__ = function.__doc__

    return model


def get_return_annotation(
    function: Callable[..., Any],
    default: Any = None,
) -> Any:
    hints = typing.get_type_hints(function)
    return hints.get("return", default)


type RecursiveIterable[T] = Iterable[T | RecursiveIterable[T]]
type MaybeRecursiveIterable[T] = T | RecursiveIterable[T]


def flatten[T](value: RecursiveIterable[T]) -> Iterator[T]:
    for current in value:
        if is_true_iterable(current):
            yield from flatten(current)
        else:
            yield current


def sqlorf(
    *expressions: Iterable[SQLColumnExpression[bool]],
) -> SQLColumnExpression[bool]:
    from sqlalchemy import or_

    return or_(False, *flatten(expressions))


def match_value[T](value: T, possibilities: MaybeSequence[T] | None = None) -> bool:
    if possibilities is None:
        return True

    return value in as_sequence(possibilities)


class MatchMode(Enum):
    EQUALS = 0
    CONTAINS = 1
    PREFIX = 2
    SUFFIX = 3


def match_string[T: (str, bytes)](
    value: T,
    possibilities: MaybeSequence[T] | None,
    mode: MatchMode,
    *,
    insensitive: bool = False,
) -> bool:
    if possibilities is None:
        return True

    possibilities = as_sequence(possibilities)
    if not possibilities:
        return False

    if insensitive:
        value = value.lower()
        possibilities = [current.lower() for current in possibilities]

    match mode:
        case MatchMode.EQUALS:
            return value in possibilities
        case MatchMode.CONTAINS:
            return any(current in value for current in possibilities)
        case MatchMode.PREFIX:
            return any(value.startswith(current) for current in possibilities)
        case MatchMode.SUFFIX:
            return any(value.endswith(current) for current in possibilities)

    raise ValueError(f"invalid mode: {mode!r}")


def sql_match_value[T](
    expression: SQLColumnExpression[T],
    value: MaybeSequence[T],
) -> SQLColumnExpression[bool]:
    return expression.in_(as_sequence(value))


def _escape_like_expression[T: (str, bytes)](text: T, escape: str) -> T:
    if isinstance(text, bytes):
        return text.replace(b"%", escape.encode() + b"%").replace(b"_", escape.encode() + b"_")
    else:
        return text.replace("%", escape + "%").replace("_", escape + "_")


def sql_match_string[T: (str, bytes)](
    expression: SQLColumnExpression[T],
    value: MaybeSequence[T],
    mode: MatchMode,
    *,
    insensitive: bool = False,
) -> SQLColumnExpression[bool]:
    import sqlalchemy

    values = as_sequence(value)
    if not values:
        return sqlalchemy.false()

    values = [_escape_like_expression(value, "^") for value in values]

    def like(current: str | bytes) -> SQLColumnExpression[bool]:
        if insensitive:
            return expression.ilike(current, escape="^")
        else:
            return expression.like(current, escape="^")

    wildcard: Any = b"%" if isinstance(values[0], bytes) else "%"

    if mode == MatchMode.EQUALS:
        if insensitive:
            return sqlorf(like(current) for current in values)
        else:
            return expression.in_(values)

    if all(value == "" or value == b"" for value in values):
        return sqlalchemy.true()

    match mode:
        case MatchMode.CONTAINS:
            return sqlorf(like(wildcard + current + wildcard) for current in values)
        case MatchMode.PREFIX:
            return sqlorf(like(current + wildcard) for current in values)
        case MatchMode.SUFFIX:
            return sqlorf(like(wildcard + current) for current in values)

    raise ValueError(f"invalid mode: {mode!r}")


BytesLike: TypeAlias = str | bytes | bytearray | memoryview


def bytes_of(data: BytesLike) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


_K = TypeVar("_K")
_V = TypeVar("_V")


def _hash(value: object) -> Hashable:
    if isinstance(value, Hashable):
        return hash(value)

    return id(value)


def uniquify[T](iterable: Iterable[T], key: Callable[[T], Hashable] | None = None) -> Iterable[T]:
    if key is None:
        key = _hash

    seen: set[Hashable] = set()

    for value in iterable:
        identity = key(value)
        if identity in seen:
            continue

        seen.add(identity)
        yield value


def group_by[K, V](iterable: Iterable[V], key: Callable[[V], K]) -> Iterable[tuple[K, list[V]]]:
    groups: defaultdict[K, list[V]] = defaultdict(list)
    for value in iterable:
        groups[key(value)].append(value)
    for item in groups.items():
        yield item


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres.database import Database
else:
    Database = object
    AsyncSession = object


_CallableT = TypeVar("_CallableT", bound=Callable[..., Any])

if TYPE_CHECKING:
    from pydantic._internal._validate_call import ValidateCallWrapper
else:
    ValidateCallWrapper = object

DEFAULT_VALIDATED_FUNCTION_CONFIG = ConfigDict(
    arbitrary_types_allowed=True,
    populate_by_name=True,
    extra="forbid",
)


def create_validated_function(
    __func: Callable[..., Any],
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> ValidateCallWrapper:
    config = {
        **DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }
    return validate_call(config=config, validate_return=validate_return)(__func)  # type: ignore


@overload
def validated_function(
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> Callable[[_CallableT], _CallableT]: ...


@overload
def validated_function(__func: _CallableT) -> _CallableT: ...


def validated_function(
    __func: _CallableT | None = None,
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> _CallableT | Callable[[_CallableT], _CallableT]:
    config = {
        **DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }
    return validate_call(config=config, validate_return=validate_return)(__func)  # type: ignore


@overload
def get_type_adapter[T](type_: type[T]) -> TypeAdapter[T]: ...


@overload
def get_type_adapter[T](type_: T) -> TypeAdapter[T]: ...


@cached(max_size=500)
def get_type_adapter[T](type_: type[T] | T) -> TypeAdapter[T]:
    return TypeAdapter(type_)


def get_traceback(exception: BaseException) -> list[str]:
    import traceback

    return traceback.format_exception(exception)


def strlist(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value

    return list(value)


@overload
def as_sequence[T: Stringy](value: T) -> Sequence[T]: ...


@overload
def as_sequence[T](value: T | Sequence[T]) -> Sequence[T]: ...


def as_sequence[T](value: T | Sequence[T]) -> Sequence[T]:
    if is_true_sequence(value):
        return value

    return (value,)


def upper_camel(string: str) -> str:
    return "".join(segment.capitalize() for segment in string.replace("_", "-").split("-"))


def lower_camel(string: str) -> str:
    if string == "":
        return string

    return string[0].lower() + upper_camel(string)[1:]


Undefined = object()

PathLike = str | _BasePathLike[str]


def call_partial[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    import inspect

    parameters = inspect.signature(function).parameters
    arity = len(
        [
            current
            for current in parameters.values()
            if current.kind != inspect.Parameter.KEYWORD_ONLY
        ]
    )

    applied_args = args[:arity]
    applied_kwargs: dict[str, Any] = {}

    for key, value in kwargs.items():
        parameter = parameters.get(key)
        if parameter is not None and parameter.kind != inspect.Parameter.POSITIONAL_ONLY:
            applied_kwargs[key] = value

    return function(*applied_args, **applied_kwargs)  # type: ignore


_T = TypeVar("_T")
_S = TypeVar("_S")


class OrderedSet(set[_T]):
    __slots__ = ("_list",)

    _list: List[_T]

    def __init__(self, d: Optional[Iterable[_T]] = None) -> None:
        if d is not None:
            self._list = list(uniquify(d))
            super().update(self._list)
        else:
            self._list = []

    @override
    def copy(self) -> OrderedSet[_T]:
        cp = self.__class__()
        cp._list = self._list.copy()
        set.update(cp, cp._list)
        return cp

    @override
    def add(self, element: _T) -> None:
        if element not in self:
            self._list.append(element)
        super().add(element)

    @override
    def remove(self, element: _T) -> None:
        super().remove(element)
        self._list.remove(element)

    @override
    def pop(self) -> _T:
        try:
            value = self._list.pop()
        except IndexError:
            raise KeyError("pop from an empty set") from None
        super().remove(value)
        return value

    def insert(self, pos: int, element: _T) -> None:
        if element not in self:
            self._list.insert(pos, element)
        super().add(element)

    @override
    def discard(self, element: _T) -> None:
        if element in self:
            self._list.remove(element)
            super().remove(element)

    @override
    def clear(self) -> None:
        super().clear()
        self._list = []

    def __getitem__(self, key: int) -> _T:
        return self._list[key]

    @override
    def __iter__(self) -> Iterator[_T]:
        return iter(self._list)

    def __add__(self, other: Iterator[_T]) -> OrderedSet[_T]:
        return self.union(other)

    @override
    def __repr__(self) -> str:
        return "%s(%r)" % (self.__class__.__name__, self._list)

    __str__ = __repr__

    @override
    def update(self, *iterables: Iterable[_T]) -> None:
        for iterable in iterables:
            for e in iterable:
                if e not in self:
                    self._list.append(e)
                    super().add(e)

    @override
    def __ior__(self, other: AbstractSet[_S]) -> OrderedSet[Union[_T, _S]]:  # type: ignore
        self.update(other)  # type: ignore
        return self  # type: ignore

    @override
    def union(self, *other: Iterable[_S]) -> OrderedSet[Union[_T, _S]]:
        result: OrderedSet[Union[_T, _S]] = self.copy()  # type: ignore
        result.update(*other)
        return result

    @override
    def __or__(self, other: AbstractSet[_S]) -> OrderedSet[Union[_T, _S]]:
        return self.union(other)

    @override
    def intersection(self, *other: Iterable[Any]) -> OrderedSet[_T]:
        other_set: Set[Any] = set()
        other_set.update(*other)
        return self.__class__(a for a in self if a in other_set)

    @override
    def __and__(self, other: AbstractSet[object]) -> OrderedSet[_T]:
        return self.intersection(other)

    @override
    def symmetric_difference(self, other: Iterable[_T]) -> OrderedSet[_T]:
        collection: Collection[_T]
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
    def __xor__(self, other: AbstractSet[_S]) -> OrderedSet[Union[_T, _S]]:
        return cast(OrderedSet[Union[_T, _S]], self).symmetric_difference(other)

    @override
    def difference(self, *other: Iterable[Any]) -> OrderedSet[_T]:
        other_set = super().difference(*other)
        return self.__class__(a for a in self._list if a in other_set)

    @override
    def __sub__(self, other: AbstractSet[Optional[_T]]) -> OrderedSet[_T]:
        return self.difference(other)

    @override
    def intersection_update(self, *other: Iterable[Any]) -> None:
        super().intersection_update(*other)
        self._list = [a for a in self._list if a in self]

    @override
    def __iand__(self, other: AbstractSet[object]) -> OrderedSet[_T]:
        self.intersection_update(other)
        return self

    @override
    def symmetric_difference_update(self, other: Iterable[Any]) -> None:
        collection = other if isinstance(other, Collection) else list(other)
        super().symmetric_difference_update(collection)
        self._list = [a for a in self._list if a in self]
        self._list += [a for a in collection if a in self]

    @override
    def __ixor__(self, other: AbstractSet[_S]) -> OrderedSet[Union[_T, _S]]:  # type: ignore
        self.symmetric_difference_update(other)
        return cast(OrderedSet[Union[_T, _S]], self)

    @override
    def difference_update(self, *other: Iterable[Any]) -> None:
        super().difference_update(*other)
        self._list = [a for a in self._list if a in self]

    def __isub__(self, other: AbstractSet[Optional[_T]]) -> OrderedSet[_T]:  # type: ignore  # noqa: E501
        self.difference_update(other)
        return self


class OrderedWeakSet[T](WeakSet[T]):
    def __init__(self, data: Iterable[T] | None = None) -> None:
        super().__init__()
        self.data = OrderedSet() if data is None else OrderedSet(ref(current) for current in data)


WeakRef = ref


def blackhole(any: Any, /) -> None:
    pass


if TYPE_CHECKING:
    from ceres.component import Component, ComponentSystem
    from ceres.engine import Engine


@overload
def as_component(obj: ComponentSystem | Component, /) -> Component: ...


@overload
def as_component(obj: ComponentSystem | Component | None, /) -> Component | None: ...


def as_component(obj: ComponentSystem | Component | None, /) -> Component | None:
    from ceres.component import Component, ComponentSystem

    if isinstance(obj, Component):
        return obj
    if not isinstance(obj, ComponentSystem):
        return None

    return obj.component


@overload
def as_component_system(obj: ComponentSystem | Component, /) -> ComponentSystem: ...


@overload
def as_component_system(obj: ComponentSystem | Component | None, /) -> ComponentSystem | None: ...


@overload
def as_component_system(obj: object | None, /) -> ComponentSystem | None: ...


def as_component_system(obj: object | None, /) -> ComponentSystem | None:
    from ceres.component import Component, ComponentSystem

    if isinstance(obj, ComponentSystem):
        return obj
    if isinstance(obj, Component):
        return obj.system

    return None


def as_components(objects: Iterable[ComponentSystem | Component | None], /) -> list[Component]:
    components: list[Component] = []
    for current in objects:
        component = as_component(current)
        if component is not None:
            components.append(component)

    return components


def as_component_systems(
    objects: Iterable[ComponentSystem | Component | None],
    /,
) -> list[ComponentSystem]:
    systems: list[ComponentSystem] = []
    for current in objects:
        system = as_component_system(current)
        if system is not None:
            systems.append(system)

    return systems


def as_engine(obj: object | None, /) -> Engine | None:
    from ceres.engine import Engine

    if isinstance(obj, Engine):
        return obj

    return None


def model_apply_overrides[T: BaseModel](model: T, overrides: T | None) -> T:
    if overrides is None:
        return model

    update: dict[str, Any] = {}

    for attribute in overrides.model_fields_set:
        update[attribute] = getattr(overrides, attribute)

    return model.model_copy(update=update)


def model_apply_defaults[T: BaseModel](model: T, defaults: T | None) -> T:
    if defaults is None:
        return model

    update: dict[str, Any] = {}

    for attribute in defaults.model_fields_set:
        if attribute not in model.model_fields_set:
            update[attribute] = getattr(defaults, attribute)

    return model.model_copy(update=update)


def model_is_empty(model: BaseModel) -> bool:
    return not all(getattr(model, field, None) is None for field in model.model_fields_set)


_SQLITE_UNIQUE_ERROR_REGEX = re.compile(
    r"UNIQUE constraint failed: ([^ ]+)\.(?P<column>[^ ]+)",
    re.MULTILINE | re.DOTALL,
)
_POSTGRES_UNIQUE_ERROR_REGEX = re.compile(
    r".*duplicate key.*\((?P<column>[^ ]+)\)=\((?P<value>[^ ]+)\)",
    re.MULTILINE | re.DOTALL,
)


@contextmanager
def wrap_database_errors() -> Iterator[None]:
    from sqlalchemy.exc import IntegrityError, SQLAlchemyError

    from ceres.error import (
        AlreadyExistsError,
        DatabaseUnexpectedError,
        DatabaseUnreachableError,
        Failure,
    )

    try:
        yield
    except SQLAlchemyError as exception:
        try:
            from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi

            PostgresIntegrityError = AsyncAdapt_asyncpg_dbapi.IntegrityError
        except ImportError:
            PostgresIntegrityError = None

        from sqlite3 import IntegrityError as SQLiteIntegrityError

        import sqlalchemy.exc

        if isinstance(exception, sqlalchemy.exc.TimeoutError):
            raise Failure(DatabaseUnreachableError(message=str(exception)))

        if isinstance(exception, IntegrityError):
            if isinstance(exception.orig, SQLiteIntegrityError):
                match = _SQLITE_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(AlreadyExistsError(field=match.group("column")))
            elif PostgresIntegrityError is not None and isinstance(
                exception.orig, PostgresIntegrityError
            ):
                match = _POSTGRES_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(
                        AlreadyExistsError(
                            field=match.group("column"),
                            value=match.group("value"),
                        )
                    )

        raise Failure(DatabaseUnexpectedError(message=str(exception)))


class classproperty(property):
    fget: Callable[[Any], Any]

    def __init__(self, fget: Callable[[Any], Any], *arg: Any, **kw: Any):
        super().__init__(fget, *arg, **kw)
        self.__doc__ = fget.__doc__

    @override
    def __get__(self, obj: Any, cls: type | None = None) -> Any:
        return self.fget(cls)


_object_setattr = object.__setattr__


def construct_model[T: BaseModel](cls: type[T], values: Mapping[Any, Any]) -> T:
    instance = cls.__new__(cls)
    _object_setattr(instance, "__dict__", dict(values))
    _object_setattr(instance, "__pydantic_fields_set__", set(values.keys()))
    _object_setattr(instance, "__pydantic_extra__", None)

    if cls.__pydantic_post_init__:
        instance.model_post_init(None)
        if hasattr(instance, "__pydantic_private__") and instance.__pydantic_private__ is not None:
            for key, value in values.items():
                if key in instance.__private_attributes__:
                    instance.__pydantic_private__[key] = value

    return instance


async def run_in_loop[T](
    coroutine: Coroutine[T, Any, Any],
    bound_loop: AbstractEventLoop,
    running_loop: AbstractEventLoop | None = None,
):
    loop = running_loop or asyncio.get_running_loop()
    future = asyncio.run_coroutine_threadsafe(coroutine, bound_loop)
    finished = Event()

    def callback(_: object):
        finished.set()

    future.add_done_callback(callback)

    await loop.run_in_executor(None, finished.wait)
    return future.result()


if TYPE_CHECKING:
    from ceres._internal.entity import BaseEntity, BaseEntityManager
    from ceres.database import Database
    from ceres.node import Node


def get_entity_singular(Entity: type[BaseEntity]) -> str:
    if Entity.__name__ == "LogEntry":
        return "log entry"

    return Entity.__name__.lower()


def get_entity_plural(Entity: type[BaseEntity]) -> str:
    if Entity.__name__ == "LogEntry":
        return "log entries"

    return f"{Entity.__name__.lower()}s"


def _get_entity_manager_attr(Entity: type[BaseEntity]) -> str:
    if Entity.__name__ == "LogEntry":
        return "logs"

    return get_entity_plural(Entity)


def get_entity_route_name(Entity: type[BaseEntity]) -> str:
    return _get_entity_manager_attr(Entity)


def get_entity_command_name(Entity: type[BaseEntity]) -> str:
    return get_entity_route_name(Entity)


def get_entity_manager(source: Database | Node, entity: type[BaseEntity]) -> BaseEntityManager:
    return getattr(source, _get_entity_manager_attr(entity))


LINUX = platform.system() == "Linux"
MACOS = platform.system() == "Darwin"
WINDOWS = platform.system() == "Windows"


def get_temporary_directory() -> Path:
    if (MACOS or LINUX) and os.path.isdir("/tmp"):
        return Path("/tmp")

    from tempfile import gettempdir

    return Path(gettempdir())
