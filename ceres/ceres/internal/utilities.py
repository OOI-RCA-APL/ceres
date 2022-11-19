from __future__ import annotations

import asyncio
import dataclasses
import inspect
import re
import signal
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
    ClassVar,
    Iterable,
    Iterator,
    Literal,
    Mapping,
    NoReturn,
    ParamSpec,
    Protocol,
    Sequence,
    TypeGuard,
    TypeVar,
    cast,
    get_type_hints,
    overload,
    runtime_checkable,
)

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, ConstrainedStr, parse_obj_as
from pydantic.decorator import ValidatedFunction
from pydantic.utils import lenient_issubclass

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


async def awaitify(value: Awaitable[_T] | _T) -> _T:
    if inspect.isawaitable(value):
        return cast(_T, await value)

    return cast(_T, value)


def dictify(obj: object) -> dict[str, Any]:
    def includes(key: str) -> bool:
        return not key.startswith("__")

    try:
        if isinstance(obj, Mapping):
            return dict(obj)
        if is_dataclass(obj):
            return dataclasses.asdict(obj)
        if isinstance(obj, BaseModel):
            return obj.dict()
        if isinstance(obj, type):
            return {key: getattr(obj, key) for key in dir(obj) if includes(key)}
        if hasattr(obj, "__slots__"):
            return {
                name: getattr(obj, name) for name in obj.__slots__ if includes(name)  # type: ignore
            }
        return {key: value for key, value in obj.__dict__.items() if not includes(key)}
    except Exception:
        raise ValueError("object cannot be dictified")


@runtime_checkable
class DataclassLike(Protocol):
    __dataclass_fields__: ClassVar[dict[str, Any]]
    __dataclass_params__: ClassVar[Any]
    __post_init__: ClassVar[Callable[..., None]]


@runtime_checkable
class PydanticDataclassLike(DataclassLike, Protocol):
    __pydantic_run_validation__: ClassVar[bool]
    __post_init_post_parse__: ClassVar[Callable[..., None]]
    __pydantic_initialised__: ClassVar[bool]
    __pydantic_model__: ClassVar[type[BaseModel]]
    __pydantic_validate_values__: ClassVar[Callable[[DataclassLike], None]]
    __pydantic_has_field_info_default__: ClassVar[bool]


def is_dataclass(obj: object) -> TypeGuard[DataclassLike]:
    return dataclasses.is_dataclass(obj)


def is_pydantic_dataclass(obj: object) -> TypeGuard[PydanticDataclassLike]:
    return dataclasses.is_dataclass(obj) and hasattr(obj, "__pydantic_model__")


def is_json_object_type(
    type_: type,
) -> TypeGuard[DataclassLike | BaseModel | Mapping[Any, Any]]:
    return dataclasses.is_dataclass(type_) or (lenient_issubclass(type_, (BaseModel, Mapping)))


class ValidateByType:
    @classmethod
    def __get_validators__(cls) -> Iterable[Any]:
        if hasattr(super(), "__get_validators__"):
            yield from super().__get_validators__()  # type: ignore

        def validate_type(value: Any) -> Any:
            if not isinstance(value, cls):
                raise ValueError(f"must be an instance of {cls}")
            return value

        yield validate_type


def unwrap(value: _T | None) -> _T:
    assert value is not None
    return value


_FunctionT = TypeVar("_FunctionT", bound=Callable[..., Any])


def cached(function: _FunctionT) -> _FunctionT:
    return cast(_FunctionT, cache(function))


class UnreachableException(Exception):
    def __init__(self) -> None:
        self.message = "Unexpected code was reached. This is a bug."


def unreachable() -> NoReturn:
    raise UnreachableException()


def snakecase(text: str) -> str:
    text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
    text = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", text)
    return text.replace("-", "_").lower()


@cached
def get_type_annotations(obj: object) -> Mapping[str, Any]:
    return MappingProxyType(get_type_hints(obj))


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


def issubtype(subtype: type | UnionType, base: type | UnionType) -> bool:
    try:
        if subtype is base:
            return True
        if isinstance(subtype, type) and isinstance(base, type | UnionType):
            return issubclass(subtype, base)
        if isinstance(subtype, UnionType):
            return all(issubtype(arg, base) for arg in subtype.__args__)
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


def pre_validate_arguments(
    function: Callable[_P, Any],
    *args: _P.args,
    **kwargs: _P.kwargs,
) -> BaseModel:
    return ValidatedFunction(function, None).init_model_instance(*args, **kwargs)
