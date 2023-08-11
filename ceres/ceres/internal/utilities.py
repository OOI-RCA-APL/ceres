import asyncio
import dataclasses
import inspect
import math
import random
import re
import signal
from asyncio import AbstractEventLoop
from collections import OrderedDict
from contextlib import contextmanager
from datetime import timedelta
from functools import cache, wraps
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

import pydantic
import pydantic.utils
import rich
from pydantic import BaseModel, parse_obj_as
from sqlalchemy.ext.asyncio import AsyncSession
from typing_extensions import Self, overload


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
        if is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return {key: getattr(obj, key) for key in obj.__fields__.keys() if includes(key)}
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
    __pydantic_run_validation__: ClassVar[bool]
    __post_init_post_parse__: Any
    __pydantic_initialised__: ClassVar[bool]
    __pydantic_model__: ClassVar[type[BaseModel]]
    __pydantic_validate_values__: ClassVar[Callable[[DataclassLike], None]]
    __pydantic_has_field_info_default__: ClassVar[bool]


def is_dataclass(obj: object) -> TypeGuard[DataclassLike]:
    return dataclasses.is_dataclass(obj)


def is_pydantic_dataclass(obj: object) -> TypeGuard[PydanticDataclassLike]:
    return dataclasses.is_dataclass(obj) and hasattr(obj, "__pydantic_model__")


ModelLike = BaseModel | PydanticDataclassLike


def get_model(obj: Any) -> type[BaseModel] | None:
    if not lenient_isinstance(obj, type):
        obj = type(obj)

    try:
        return pydantic.utils.get_model(cast(Any, obj))
    except Exception:
        return None


def has_field(obj: Any, name: str, type: Any = None) -> bool:
    name = snakecase(name)

    if dataclasses.is_dataclass(obj):
        return any(
            field.name == name and (type is None or is_subtype(field.type, type))
            for field in dataclasses.fields(obj)
        )
    if isinstance(obj, BaseModel) or issubclass(obj, BaseModel):
        return any(
            field.name == name and (type is None or is_subtype(field.outer_type_, type))
            for field in obj.__fields__.values()
        )

    return False


class ValidateByType:
    @classmethod
    def __get_validators__(cls) -> Iterable[Callable[[Any], Self]]:
        if hasattr(super(), "__get_validators__"):
            yield from super().__get_validators__()  # type: ignore
        yield cls.__validate

    @classmethod
    def __validate(cls, value: Any) -> Self:
        if not isinstance(value, cls):
            raise ValueError(f"must be an instance of {strify(cls)}, got {strify(type(value))}")

        return value


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
    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    def get_exception() -> ValueError:
        return ValueError(
            "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
            "'ms', 's', 'm', 'h' or 'd'."
        )

    if not isinstance(value, str):
        raise get_exception()

    try:
        return parse_obj_as(timedelta, value)
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

    if isinstance(obj, BaseModel) or is_dataclass(obj):
        model = get_model(obj)
        if model is not None:
            for name in model.__fields__.keys():
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
    rich.print(value)
    return value


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def cached(function: _FunctionT) -> _FunctionT:
    return cast(_FunctionT, cache(function))


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


if TYPE_CHECKING:
    from ceres.database import Database


async def get_session(database: "Database", session: AsyncSession | None) -> AsyncSession:
    if session is None:
        return await database.init()
    return session
