import asyncio
import dataclasses

import inspect
import math
import random
import re
import signal
import sys
import textwrap
import typing
from asyncio import AbstractEventLoop, Task
from collections import OrderedDict, defaultdict
from contextlib import contextmanager
from datetime import timedelta
from functools import lru_cache, wraps
from os import PathLike as _BasePathLike
from types import NoneType, UnionType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Awaitable,
    ByteString,
    Callable,
    ClassVar,
    Collection,
    Coroutine,
    Hashable,
    Iterable,
    Iterator,
    Mapping,
    ParamSpec,
    Protocol,
    Sequence,
    TypeAlias,
    TypeGuard,
    TypeVar,
    cast,
)

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, create_model
from pydantic.fields import FieldInfo
from pydantic.validate_call import validate_call
from pydantic_core import CoreSchema, SchemaSerializer, SchemaValidator
from typing_extensions import overload

NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"


def strify(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return "<__str__() raised exception>"


_P = ParamSpec("_P")
_T = TypeVar("_T")


def syncify(function: Callable[_P, Awaitable[_T] | _T]) -> Callable[_P, _T]:
    if not inspect.iscoroutinefunction(function):
        return cast(Callable[_P, _T], function)

    @wraps(function)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
        return ensure_event_loop().run_until_complete(function(*args, **kwargs))

    return cast(Callable[_P, _T], wrapper)


async def awaitify(value: Awaitable[_T] | _T) -> _T:
    if inspect.isawaitable(value):
        return cast(_T, await value)

    return cast(_T, value)


def dictify(obj: object) -> dict[str, Any]:
    def includes(key: str) -> bool:
        return not key.startswith("__")

    try:
        if is_mapping(obj):
            return dict(obj)
        if is_dataclass_instance(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return {key: getattr(obj, key) for key in obj.model_fields.keys() if includes(key)}
        if isinstance(obj, type):
            return {key: getattr(obj, key) for key in dir(obj) if includes(key)}
        slots: tuple[str, ...] | None = getattr(obj, "__slots__", None)
        if slots is not None:
            return {name: getattr(obj, name) for name in slots if includes(name)}
        return {key: value for key, value in obj.__dict__.items() if includes(key)}
    except Exception:
        raise ValueError("object cannot be dictified")


class DataclassLike(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]
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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        ...


def is_dataclass_instance(obj: object) -> TypeGuard[DataclassLike]:
    return not isinstance(obj, type) and is_dataclass(obj)


def is_dataclass_type(obj: object) -> TypeGuard[DataclassLike]:
    return isinstance(obj, type) and is_dataclass(obj)


def is_dataclass(obj: object) -> TypeGuard[DataclassLike | type[DataclassLike]]:
    return dataclasses.is_dataclass(obj)


def is_pydantic_dataclass_type(obj: object) -> TypeGuard[type[PydanticDataclassLike]]:
    return isinstance(obj, type) and is_pydantic_dataclass(obj)


def is_pydantic_dataclass_instance(obj: object) -> TypeGuard[PydanticDataclassLike]:
    return not isinstance(obj, type) and is_pydantic_dataclass(obj)


def is_pydantic_dataclass(
    obj: object,
) -> TypeGuard[PydanticDataclassLike | type[PydanticDataclassLike]]:
    return dataclasses.is_dataclass(obj) and hasattr(obj, "__pydantic_core_schema__")


ModelLike = BaseModel | PydanticDataclassLike


def has_field(obj: Any, name: str, type: Any = None) -> bool:
    name = snakecase(name)

    if is_dataclass_instance(obj):
        return any(
            field.name == name and (type is None or is_subtype(field.type, type))
            for field in dataclasses.fields(obj)
        )

    if isinstance(obj, BaseModel) or issubclass(obj, BaseModel):
        field = obj.model_fields.get(name)
        if field is None:
            return False
        if type is None:
            return True
        if field.annotation is None:
            return False

        return is_subtype(field.annotation, type)

    return False


def unwrap(value: _T | None) -> _T:
    assert value is not None
    return value


def snakecase(text: str) -> str:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").lower()


def randstr(characters: str, length: int) -> str:
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


def is_subtype(subtype: type | UnionType, base: type | UnionType) -> bool:
    try:
        if subtype is base:
            return True
        if isinstance(subtype, type) and isinstance(base, type | UnionType):
            return issubclass(subtype, base)
        if isinstance(subtype, UnionType):
            return all(is_subtype(arg, base) for arg in subtype.__args__)
    except Exception:
        pass

    return False


def is_optional_type(type_: type | UnionType) -> bool:
    return is_subtype(NoneType, type_)


def is_stringy(obj: Any) -> TypeGuard[str | ByteString | memoryview]:
    return lenient_isinstance(obj, (str, ByteString, memoryview))


def is_iterable(obj: Any) -> TypeGuard[Iterable[Any]]:
    if not lenient_isinstance(obj, Iterable):
        return False

    try:
        iter(obj)
    except Exception:
        return False

    return True


def is_non_stringy_iterable(obj: Any) -> TypeGuard[Iterable[Any]]:
    return not is_stringy(obj) and is_iterable(obj)


def is_collection(obj: Any) -> TypeGuard[Collection[Any]]:
    if not lenient_isinstance(obj, Collection):
        return False

    try:
        len(obj)
        iter(obj)
    except Exception:
        return False

    return True


def is_non_stringy_collection(obj: Any) -> TypeGuard[Collection[Any]]:
    return not is_stringy(obj) and is_collection(obj)


def is_mapping(obj: Any) -> TypeGuard[Mapping[Any, Any]]:
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
        for name in obj.model_fields.keys():
            element = getattr(obj, name, None)
            traverse(element, visit, seen)
    elif is_dataclass_instance(obj):
        for name in obj.__dataclass_fields__.keys():
            element = getattr(obj, name, None)
            traverse(element, visit, seen)
    elif is_mapping(obj):
        for key, value in obj.items():
            traverse(key, visit, seen)
            traverse(value, visit, seen)
    elif is_non_stringy_collection(obj):
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
    while True:
        await asyncio.sleep(math.inf)


def get_event_loop_or_none() -> AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def ensure_event_loop() -> AbstractEventLoop:
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
            return asyncio.get_running_loop()
        except Exception:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop


@contextmanager
def temporary_signal_handler(signums: Sequence[int], handler: Callable[..., Any]) -> Iterator[None]:
    loop = get_event_loop_or_none()
    originals: dict[int, Any] = {}

    for signum in signums:
        if original := signal.getsignal(signum):
            originals[signum] = original

        if loop is not None:
            loop.add_signal_handler(signum, handler)
        else:
            signal.signal(signum, handler)

    try:
        yield
    finally:
        for signum, original in originals.items():
            signal.signal(signum, original)


def set_current_process_name(name: str) -> None:
    try:
        from setproctitle import setproctitle

        setproctitle(name)
    except Exception:
        pass


def dbg(value: _T) -> _T:
    import rich

    rich.print(value)
    return value


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


@overload
def cached(
    function: None = None, *, max_size: int | None = None
) -> Callable[[_FunctionT], _FunctionT]:
    ...


@overload
def cached(function: _FunctionT) -> _FunctionT:
    ...


def cached(
    function: _FunctionT | None = None, *, max_size: int | None = None
) -> _FunctionT | Callable[[_FunctionT], _FunctionT]:
    def cached(function: _FunctionT) -> _FunctionT:
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
    remove_self: bool = True,
) -> type[BaseModel]:
    function = get_inner_function(function)

    if model_name is None:
        model_name = f"{upper_camel(function.__name__)}Args"
    if model_config is None:
        model_config = {}

    (
        position_parameter_names,
        _,
        kwargs_parameter_name,
        positional_parameter_defaults,
        keyword_only_parameter_names,
        keyword_only_parameter_defaults,
        annotations,
    ) = inspect.getfullargspec(function)

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
    if kwargs_parameter_name:
        model_config = {**model_config, "extra": "allow"} if kwargs_parameter_name else model_config

    model = create_model(
        model_name,
        __config__=model_config,
        __module__=model_module or "__dynamic__",
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


def setattr_internal(cls: type[_T], instance: _T, name: str, value: object) -> None:
    if name.startswith("__") and not name.endswith("__"):
        name = f"_{cls.__name__}{name}"

    object.__setattr__(instance, name, value)


def getattr_internal(cls: type[_T], instance: _T, name: str, value: object) -> None:
    if name.startswith("__") and not name.endswith("__"):
        name = f"_{cls.__name__}{name}"

    object.__setattr__(instance, name, value)


@overload
def escape_like_expression(text: str) -> str:
    ...


@overload
def escape_like_expression(text: bytes) -> bytes:
    ...


def escape_like_expression(text: str | bytes) -> str | bytes:
    if isinstance(text, str):
        return text.replace("%", "%%").replace("_", "__")

    return text.replace(b"%", b"%%").replace(b"_", b"__")


BytesLike: TypeAlias = str | bytes | bytearray | memoryview


def bytes_of(data: BytesLike) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(data)


_K = TypeVar("_K")
_V = TypeVar("_V")


class CacheDict(OrderedDict[_K, _V]):
    def __init__(self, size: int = 10) -> None:
        assert size > 0
        self.cache_len = size

        super().__init__()

    def __setitem__(self, key: _K, value: _V) -> None:
        super().__setitem__(key, value)
        super().move_to_end(key)

        while len(self) > self.cache_len:
            oldkey = next(iter(self))
            super().__delitem__(oldkey)

    def __getitem__(self, key: _K) -> _V:
        val = super().__getitem__(key)
        super().move_to_end(key)

        return val


def chunkify(iterable: Iterable[_T], size: int) -> Iterable[Sequence[_T]]:
    current: list[_T] = []
    for item in iterable:
        current.append(item)
        if len(current) >= size:
            yield tuple(current)
            current.clear()

    if current:
        yield tuple(current)


async def achunkify(iterable: AsyncIterable[_T], size: int) -> AsyncIterable[Sequence[_T]]:
    current: list[_T] = []
    async for item in iterable:
        current.append(item)
        if len(current) >= size:
            yield tuple(current)
            current.clear()

    if current:
        yield tuple(current)


def _hash(value: object) -> Hashable:
    if isinstance(value, Hashable):
        return hash(value)

    return id(value)


def uniquify(iterable: Iterable[_T], key: Callable[[_T], Hashable] | None = None) -> Iterable[_T]:
    if key is None:
        key = _hash

    seen: set[Hashable] = set()

    for value in iterable:
        identity = key(value)
        if identity in seen:
            continue

        seen.add(identity)
        yield value


def group_by(iterable: Iterable[_V], key: Callable[[_V], _K]) -> Iterable[tuple[_K, list[_V]]]:
    groups: defaultdict[_K, list[_V]] = defaultdict(list)
    for value in iterable:
        groups[key(value)].append(value)
    for item in groups.items():
        yield item


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ceres.database.database import Database
else:
    Database = object
    AsyncSession = object


async def get_session(database: "Database", session: AsyncSession | None) -> AsyncSession:
    if session is None:
        return await database.init()
    return session


def sqlstmt(statement: str, *, indent: int = 0) -> str:
    statement = textwrap.dedent(statement).strip()
    import sqlparse

    sqlparse.format(statement, keyword_case="upper").strip()
    statement = statement.rstrip(";")
    statement += ";"
    if indent:
        statement = textwrap.indent(statement, " " * (indent * 4))
    return statement


def sqlexpr(statement: str, *, indent: int = 0) -> str:
    statement = textwrap.dedent(statement).strip()
    import sqlparse

    sqlparse.format(statement, keyword_case="upper").strip()
    if indent:
        statement = textwrap.indent(statement, " " * (indent * 4))
    return statement


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
) -> Callable[[_CallableT], _CallableT]:
    ...


@overload
def validated_function(__func: _CallableT) -> _CallableT:
    ...


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


@cached(max_size=500)
def get_type_adapter(type_: type[_T]) -> TypeAdapter[_T]:
    return TypeAdapter(type_)


def get_traceback(exception: BaseException) -> list[str]:
    import traceback

    return traceback.format_exception(exception)


if sys.version_info >= (3, 11):
    from enum import StrEnum as BaseStrEnum
else:
    from backports.strenum import StrEnum as BaseStrEnum


class StrEnum(BaseStrEnum):
    @staticmethod
    def _generate_next_value_(name: str, *args: Any, **kwargs: Any) -> str:
        return name.lower().replace("_", "-")


def strlist(value: str | Sequence[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return value

    return list(value)


def as_sequence(value: _T | Sequence[_T]) -> Sequence[_T]:
    if not isinstance(value, str) and isinstance(value, Sequence):
        return value

    return (value,)  # type: ignore


_O = TypeVar("_O")


@overload
def coalesce(value: _T | None, default: Callable[[], _O]) -> _T | _O:
    ...


@overload
def coalesce(value: _T | None, default: _O) -> _T | _O:
    ...


def coalesce(value: object, default: object) -> object:
    if value is None:
        if callable(default):
            return default()

        return default

    return value


def sequence(start: _T, next: Callable[[_T], _T]) -> Iterator[_T]:
    current = start
    while True:
        yield current
        current = next(start)


async def cancel(*tasks: Task[Any]) -> None:
    for delay in sequence(0, lambda current: 0.001 if current == 0 else min(current * 2, 1)):
        for task in tasks:
            task.cancel()

        for task in tasks:
            if not task.done():
                await asyncio.sleep(delay)
                continue

        break


async def _wait_many(
    condition: str,
    tasks: Sequence[Task[_T] | Coroutine[Any, Any, _T]],
) -> tuple[set[Task[_T]], set[Task[_T]]]:
    waiting = [asyncio.create_task(task) if not isinstance(task, Task) else task for task in tasks]
    result = await asyncio.wait(waiting, return_when=condition)
    return result


async def wait_any(
    *tasks: Task[_T] | Coroutine[_T, Any, Any]
) -> tuple[set[Task[_T]], set[Task[_T]]]:
    return await _wait_many(asyncio.FIRST_COMPLETED, tasks)


async def wait_all(
    *tasks: Task[_T] | Coroutine[_T, Any, Any]
) -> tuple[set[Task[_T]], set[Task[_T]]]:
    return await _wait_many(asyncio.ALL_COMPLETED, tasks)


def upper_camel(string: str) -> str:
    return "".join(segment.capitalize() for segment in string.replace("_", "-").split("-"))


Undefined = object()

PathLike = str | _BasePathLike[str]
