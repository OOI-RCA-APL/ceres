import asyncio
import dataclasses
import inspect
import operator
import os
import platform
import re
import sys
import traceback
import typing
from annotationlib import Format
from asyncio import AbstractEventLoop, Future
from collections import defaultdict
from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Coroutine,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
    Set,
    ValuesView,
)
from contextlib import contextmanager
from datetime import timedelta
from enum import Enum
from functools import wraps
from os import PathLike as _BasePathLike
from pathlib import Path
from threading import Event, RLock
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Optional,
    TypeAlias,
    cast,
    get_args,
    get_origin,
    overload,
    override,
)
from weakref import WeakKeyDictionary, WeakSet, ref

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    create_model,
    validate_call,
)

from ceres._internal.lazy import lazy_imports

if TYPE_CHECKING:
    from typing import TypeIs

    from sqlalchemy import SQLColumnExpression

    from ceres.data import MaybeSequence


with lazy_imports(__name__, export=True):
    from ceres.util import azip as azip
    from ceres.util import cancel as cancel
    from ceres.util import concurrently as concurrently
    from ceres.util import ensure_event_loop as ensure_event_loop
    from ceres.util import wait_all as wait_all
    from ceres.util import wait_any as wait_any


NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"


def strify(value: object, /) -> str:
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


def reprify(value: object, /) -> str:
    try:
        return repr(value)
    except Exception:
        return "<__repr__() raised exception>"


async def awaitify[T](value: Awaitable[T] | T, /) -> T:
    import inspect

    if inspect.isawaitable(value):
        return cast("T", await value)

    return cast("T", value)


def snakecase(text: str, /) -> str:
    """
    >>> snakecase("Hello World")
    'hello_world'
    >>> snakecase("helloWorld")
    'hello_world'
    >>> snakecase("hello-world")
    'hello_world'
    >>> snakecase("hello_world")
    'hello_world'
    >>> snakecase("HELLO")
    'hello'
    """
    from pydantic.alias_generators import to_snake

    text = text.strip()
    # Convert all runs of whitespace and hyphens to a single underscore.
    text = re.sub(r"[\s-]+", "_", text)
    return to_snake(text)


def kebabcase(text: str, /) -> str:
    """
    >>> kebabcase("Hello World")
    'hello-world'
    >>> kebabcase("helloWorld")
    'hello-world'
    >>> kebabcase("hello-world")
    'hello-world'
    >>> kebabcase("hello_world")
    'hello-world'
    >>> kebabcase("HELLO")
    'hello'
    """
    return snakecase(text).replace("_", "-")


def ucamelcase(text: str, /) -> str:
    """
    >>> upper_camelcase("Hello World")
    'HelloWorld'
    >>> upper_camelcase("helloWorld")
    'HelloWorld'
    >>> upper_camelcase("hello-world")
    'HelloWorld'
    >>> upper_camelcase("hello_world")
    'HelloWorld'
    >>> upper_camelcase("HELLO")
    'Hello'
    """
    from pydantic.alias_generators import to_camel

    text = text.strip()
    # Convert all runs of whitespace and hyphens to a single underscore.
    text = re.sub(r"[\s-]+", "_", text)
    text = to_camel(text)
    if not text:
        return ""

    return text[0].upper() + text[1:]  # Capitalize the first letter.


def titlecase(string: str, /) -> str:
    """
    >>> titlecase("Hello World")
    'Hello World'
    >>> titlecase("helloWorld")
    'Hello World'
    >>> titlecase("hello-world")
    'Hello World'
    >>> titlecase("hello_world")
    'Hello World'
    >>> titlecase("HELLO")
    'Hello'
    """
    return " ".join(segment.capitalize() for segment in snakecase(string).split("_"))


def randstr(characters: str, length: int, /) -> str:
    import random

    return "".join(random.choice(characters) for _ in range(length))


_DELTA_MS = timedelta(milliseconds=1)
_DELTA_S = timedelta(seconds=1)
_DELTA_M = timedelta(minutes=1)
_DELTA_H = timedelta(hours=1)
_DELTA_D = timedelta(days=1)


def encode_td(
    value: timedelta,
    /,
    *,
    decimals: int | None = None,
    space: bool = False,
) -> str:
    if value < _DELTA_MS:
        number, unit = float(value.microseconds), "us"
    elif value < _DELTA_S:
        number, unit = value.microseconds / 1000, "ms"
    elif value < _DELTA_M:
        number, unit = value.total_seconds(), "s"
    elif value < _DELTA_H:
        number, unit = value.total_seconds() / 60, "m"
    elif value < _DELTA_D:
        number, unit = value.total_seconds() / (60 * 60), "h"
    else:
        number, unit = value.total_seconds() / (60 * 60 * 24), "d"

    if decimals is not None:
        number_text = f"{number:.{decimals}f}"
    else:
        number_text = f"{number}"

    number_text = number_text.rstrip("0").rstrip(".")

    if space:
        return f"{number_text} {unit}"
    else:
        return f"{number_text}{unit}"


def decode_td(value: str | timedelta | int | float | Any, /) -> timedelta:
    from ceres.data import validate

    if isinstance(value, timedelta):
        return value

    def get_exception() -> ValueError:
        return ValueError(
            "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
            "'ms', 's', 'm', 'h' or 'd'."
        )

    if isinstance(value, str):
        try:
            return validate(value, timedelta)
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
            decoded_value = float(value[: -len(decoded_unit)].strip())
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

    if isinstance(value, int | float):
        return timedelta(seconds=value)

    raise get_exception()


Stringy: TypeAlias = str | bytes | bytearray | memoryview


def is_stringy(obj: Any, /) -> TypeIs[Stringy]:
    if obj is None:
        return False

    return isinstance(obj, Stringy)


def is_iterable(obj: Any, /) -> TypeIs[Iterable[Any]]:
    if obj is None:
        return False
    if not isinstance(obj, Iterable):
        return False

    try:
        iter(obj)
    except Exception:
        return False

    return True


def is_true_iterable(obj: Any, /) -> TypeIs[Iterable[Any]]:
    return is_iterable(obj) and not is_stringy(obj) and not isinstance(obj, Future)


def is_collection(obj: Any, /) -> TypeIs[Collection[Any]]:
    if obj is None:
        return False
    if isinstance(obj, list | tuple | set | frozenset):
        return True
    if not isinstance(obj, Collection):
        return False

    try:
        len(obj)
        iter(obj)
    except Exception:
        return False

    return True


def is_true_collection(obj: Any, /) -> TypeIs[Collection[Any]]:
    return is_collection(obj) and not is_stringy(obj)


def is_sequence(obj: Any, /) -> TypeIs[Sequence[Any]]:
    if obj is None:
        return False
    if isinstance(obj, list | tuple):
        return True
    if not isinstance(obj, Sequence):
        return False

    try:
        len(obj)
        iter(obj)
    except Exception:
        return False

    return True


def is_true_sequence(obj: Any, /) -> TypeIs[Sequence[Any]]:
    return is_sequence(obj) and not is_stringy(obj)


def is_mapping(obj: Any, /) -> TypeIs[Mapping[Any, Any]]:
    if obj is None:
        return False
    if isinstance(obj, dict):
        return True
    if not isinstance(obj, Mapping):
        return False

    try:
        obj.keys()
    except Exception:
        return False

    return True


def traverse(
    obj: object,
    /,
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

    undefined = object()
    if isinstance(obj, BaseModel):
        for field_name, field in obj.__class__.model_fields.items():
            element = getattr(obj, field_name, undefined)
            if element is not undefined:
                traverse(element, visit, seen)
    elif not isinstance(obj, type) and dataclasses.is_dataclass(obj):
        for field in dataclasses.fields(obj):
            element = getattr(obj, field.name, undefined)
            if element is not undefined:
                traverse(element, visit, seen)
    elif is_mapping(obj):
        for key, value in obj.items():
            traverse(key, visit, seen)
            traverse(value, visit, seen)
    elif is_true_collection(obj):
        for value in obj:
            traverse(value, visit, seen)


if TYPE_CHECKING:
    from builtins import isinstance as lenient_isinstance
    from builtins import issubclass as lenient_issubclass
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


def dbg[T](value: T, /) -> T:
    import rich

    rich.print(value)
    return value


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

        storage = WeakKeyDictionary()
    elif storage is None:
        storage = {}

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


def get_function_name(function: Callable[..., Any], /) -> str:
    original = function.__name__

    if function.__name__.startswith("__") and not function.__name__.endswith("__"):
        tokens = function.__qualname__.split(".")
        if len(tokens) < 2:
            return original

        return f"_{tokens[-2]}{original}"

    return original


def get_inner_function(function: Callable[..., Any], /) -> Callable[..., Any]:
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
    /,
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
        model_name = f"{ucamelcase(function.__name__)}Args"

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


def flatten[T](value: RecursiveIterable[T], /) -> Iterator[T]:
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

    return value in seq(possibilities)


class MatchMode(Enum):
    EQUALS = 0
    CONTAINS = 1
    PREFIX = 2
    SUFFIX = 3


def match_string[T: (str, bytes)](
    value: T | None,
    possibilities: MaybeSequence[T] | None,
    mode: MatchMode,
    *,
    insensitive: bool = False,
) -> bool:
    if possibilities is None:
        return True

    if value is None:
        return False

    possibilities = seq(possibilities)
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
    return expression.in_(seq(value))


def _escape_like_expression[T: (str, bytes)](text: T, escape: str) -> T:
    if isinstance(text, bytes):
        return text.replace(b"%", escape.encode() + b"%").replace(b"_", escape.encode() + b"_")
    else:
        return text.replace("%", escape + "%").replace("_", escape + "_")


def sql_match_string[T: (str, bytes)](
    expression: SQLColumnExpression[T | None],
    value: MaybeSequence[T],
    mode: MatchMode,
    *,
    insensitive: bool = False,
) -> SQLColumnExpression[bool]:
    import sqlalchemy

    values = seq(value)
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


def tokenize_bytes(value: bytes, /) -> str:
    if not value:
        return ""

    return value.hex(b" ") + " "


def _hash(value: object, /) -> Hashable:
    if isinstance(value, Hashable):
        return hash(value)

    return id(value)


def uniquify[T](
    iterable: Iterable[T],
    /,
    key: Callable[[T], Hashable] | None = None,
) -> Iterable[T]:
    if key is None:
        key = _hash

    seen: set[Hashable] = set()

    for value in iterable:
        identity = key(value)
        if identity in seen:
            continue

        seen.add(identity)
        yield value


def group_by[K, V](
    iterable: Iterable[V],
    /,
    key: Callable[[V], K],
) -> Iterable[tuple[K, list[V]]]:
    groups: defaultdict[K, list[V]] = defaultdict(list)
    for value in iterable:
        groups[key(value)].append(value)
    yield from groups.items()


if TYPE_CHECKING:
    from ceres.database import Database
else:
    Database = object


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
    function: Callable[..., Any],
    /,
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> ValidateCallWrapper:
    config = {
        **DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }
    return validate_call(config=config, validate_return=validate_return)(function)  # type: ignore


@overload
def validated_function[T: Callable[..., Any]](
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> Callable[[T], T]: ...


@overload
def validated_function[T: Callable[..., Any]](function: T, /) -> T: ...


def validated_function[T: Callable[..., Any]](
    function: T | None = None,
    /,
    *,
    config: ConfigDict | None = None,
    validate_return: bool = False,
) -> T | Callable[[T], T]:
    config = {
        **DEFAULT_VALIDATED_FUNCTION_CONFIG,
        **(config or {}),
    }
    return validate_call(config=config, validate_return=validate_return)(function)  # type: ignore


def get_traceback(exception: BaseException) -> list[str]:
    import traceback

    return traceback.format_exception(exception)


@overload
def seq[T: Stringy](value: T, /) -> Sequence[T]: ...


@overload
def seq[T](value: T | Sequence[T], /) -> Sequence[T]: ...


def seq[T](value: T | Sequence[T], /) -> Sequence[T]:
    if is_true_sequence(value):
        return value

    return (value,)


class UndefinedType(Enum):
    Instance = 0


Undefined = UndefinedType.Instance

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


class OrderedSet[T](set[T]):
    __slots__ = ("_list",)

    _list: list[T]

    @override
    def __init__(self, values: Iterable[T] | None = None, /) -> None:
        if values is not None:
            self._list = list(uniquify(values))
            super().update(self._list)
        else:
            self._list = []

    @override
    def copy(self) -> OrderedSet[T]:
        cp = self.__class__()
        cp._list = self._list.copy()
        set.update(cp, cp._list)
        return cp

    @override
    def add(self, element: T) -> None:
        if element not in self:
            self._list.append(element)
        super().add(element)

    @override
    def remove(self, element: T) -> None:
        super().remove(element)
        self._list.remove(element)

    @override
    def pop(self) -> T:
        try:
            value = self._list.pop()
        except IndexError:
            raise KeyError("pop from an empty set") from None
        super().remove(value)
        return value

    def insert(self, pos: int, element: T) -> None:
        if element not in self:
            self._list.insert(pos, element)
        super().add(element)

    @override
    def discard(self, element: T) -> None:
        if element in self:
            self._list.remove(element)
            super().remove(element)

    @override
    def clear(self) -> None:
        super().clear()
        self._list = []

    def __getitem__(self, key: int) -> T:
        return self._list[key]

    @override
    def __iter__(self) -> Iterator[T]:
        return iter(self._list)

    def __add__(self, other: Iterator[T]) -> OrderedSet[T]:
        return self.union(other)

    @override
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._list!r})"

    __str__ = __repr__

    @override
    def update(self, *iterables: Iterable[T]) -> None:
        for iterable in iterables:
            for e in iterable:
                if e not in self:
                    self._list.append(e)
                    super().add(e)

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
        return self.__class__(a for a in self._list if a in other_set)

    @override
    def __sub__(self, other: Set[T | None]) -> OrderedSet[T]:
        return self.difference(other)

    @override
    def intersection_update(self, *other: Iterable[Any]) -> None:
        super().intersection_update(*other)
        self._list = [a for a in self._list if a in self]

    @override
    def __iand__(self, other: Set[object]) -> OrderedSet[T]:
        self.intersection_update(other)
        return self

    @override
    def symmetric_difference_update(self, other: Iterable[Any]) -> None:
        collection = other if isinstance(other, Collection) else list(other)
        super().symmetric_difference_update(collection)
        self._list = [a for a in self._list if a in self]
        self._list += [a for a in collection if a in self]

    @override
    def __ixor__[O](self, other: Set[O]) -> OrderedSet[T | O]:  # type: ignore
        self.symmetric_difference_update(other)
        return cast("OrderedSet[T | O]", self)

    @override
    def difference_update(self, *other: Iterable[Any]) -> None:
        super().difference_update(*other)
        self._list = [a for a in self._list if a in self]

    def __isub__(self, other: Set[T | None]) -> OrderedSet[T]:  # type: ignore  # noqa: E501
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


_SQLITE_UNIQUE_ERROR_REGEX = re.compile(
    r"UNIQUE constraint failed: (.+?)\.(?P<column>.+?)",
    re.MULTILINE | re.DOTALL,
)
_POSTGRES_UNIQUE_ERROR_REGEX = re.compile(
    r".*duplicate key.*\((?P<column>.+?)\)=\((?P<value>.+?)\)",
    re.MULTILINE | re.DOTALL,
)


@contextmanager
def wrap_database_errors() -> Iterator[None]:
    from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
    from sqlalchemy.exc import SQLAlchemyError

    from ceres.error import (
        AlreadyExistsError,
        DatabaseProgrammingError,
        DatabaseUnexpectedError,
        DatabaseUnreachableError,
        Failure,
        IntegrityError,
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

        if isinstance(
            exception,
            sqlalchemy.exc.ArgumentError | sqlalchemy.exc.InvalidRequestError,
        ):
            raise Failure(
                DatabaseProgrammingError(
                    message=str(exception),
                    traceback=traceback.format_exception(exception),
                )
            )

        if isinstance(exception, sqlalchemy.exc.TimeoutError):
            raise Failure(DatabaseUnreachableError(message=str(exception)))

        if isinstance(exception, SQLAlchemyIntegrityError):
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

            raise Failure(IntegrityError)

        raise Failure(DatabaseUnexpectedError(message=str(exception)))


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
        # Assigning the class property with an annotation in a dataclass's body will cause the class
        # property to be computed immediately as the dataclass is being built, which is bad and will
        # likely cause errors. Removing the annotation allows specifying a type annotation when
        # using the assignment syntax without it causing issues.
        definer.__annotations__.pop(name, None)

    def __get__(self, obj: C | None, owner: type[C], /) -> V:
        return self.fget(owner)

    def __invert__(self) -> Any:
        return self


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


_object_setattr = object.__setattr__


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
    from ceres._internal.entity import BaseEntityManager
    from ceres.database import Database
    from ceres.entity import Entity
    from ceres.node import Node


def get_entity_manager(source: Database | Node, entity: type[Entity]) -> BaseEntityManager:
    naming = entity.__naming__
    manager = getattr(source, naming.manager, None)
    if manager is None:
        raise ValueError(
            f"Object `{source}` has no manager for {entity} at attribute {naming.manager!r}."
        )

    return manager


LINUX = platform.system() == "Linux"
MACOS = platform.system() == "Darwin"
WINDOWS = platform.system() == "Windows"
UNIX = not WINDOWS
FREE_THREADED = "free" in sys.version


def get_temporary_directory() -> Path:
    if UNIX and os.path.isdir("/tmp"):
        return Path("/tmp")

    from tempfile import gettempdir

    return Path(gettempdir())


@contextmanager
def temporary_signal_handler(signums: Sequence[int], handler: Callable[..., Any]):
    import signal

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


if __name__ == "__main__":
    from doctest import testmod

    testmod()


def is_subtype(subtype: Any, supertype: Any, /) -> bool:
    # If the supertype is a union, check if any of the contained types are subtypes.
    if isinstance(supertype, UnionType):
        for current in get_args(supertype):
            if is_subtype(subtype, current):
                return True

        return False

    origin = get_origin(supertype)
    try:
        args = get_args(supertype)
    except Exception:
        args = ()

    # If the supertype is `Annotated` or `Optional`, check if the inner type is assignable.
    if args and (origin is Annotated or origin is Optional):
        inner = args[0]
        if is_subtype(subtype, inner):
            return True

    # If the supertype is a type alias, check if the contained type is assignable.
    try:
        from typing import TypeAliasType

        if isinstance(supertype, TypeAliasType):
            return is_subtype(supertype.__value__, subtype)
    except ImportError:
        pass

    # Finally, check if the subtype is a just class that is a subclass of the supertype.
    return (
        isinstance(supertype, type) and isinstance(subtype, type) and issubclass(subtype, supertype)
    )


class RequireSlots:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if cls.__module__.startswith("ceres."):
            if "__slots__" not in cls.__dict__:
                raise TypeError(f"{cls} must define `__slots__`.")


def declared_slots_of(cls: type) -> list[str]:
    slots: dict[str, None] = {}

    for current in reversed(cls.__mro__):
        __slots__ = getattr(current, "__slots__", ())
        if isinstance(__slots__, str):
            __slots__ = (__slots__,)
        for slot in __slots__:
            slots[slot] = None

    return list(slots)


class LRUCache[K, V](MutableMapping[K, V]):
    __slots__ = (
        "capacity",
        "threshold",
        "size_alert",
        "_data",
        "_counter",
        "_mutex",
    )

    capacity: int
    threshold: float
    size_alert: Callable[[LRUCache[K, V]], None] | None

    def __init__(
        self,
        capacity: int = 100,
        threshold: float = 0.5,
        size_alert: Callable[..., None] | None = None,
    ):
        import threading

        self.capacity = capacity
        self.threshold = threshold
        self.size_alert = size_alert
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
            size_alert = bool(self.size_alert)
            while len(self) > self.capacity + self.capacity * self.threshold:
                if size_alert:
                    size_alert = False
                    self.size_alert(self)  # type: ignore
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
