"""Helper types, type aliases, enums, and validators."""

from __future__ import annotations

__all__ = [
    "Username",
    "Password",
    "EmailAddress",
    "BCryptHash",
    "Argon2Hash",
    "PasswordHash",
    "StrEnum",
    "OrderedStrEnum",
    "RegexFlags",
    "ToBytes",
    "AsBytes",
    "Name",
    "NonEmptyStr",
    "NonBlankStr",
    "Date",
    "Time",
    "DateTimeInput",
    "DateTime",
    "TimeDeltaInput",
    "TimeDelta",
    "PositiveTimeDelta",
    "NonNegativeTimeDelta",
    "FromJSON",
    "FromYAML",
    "Number",
    "JSONValue",
    "JSONDict",
    "JSONList",
    "JSONSerializable",
    "JSONSerializableDict",
    "JSONSerializableList",
    "MaybeList",
    "MaybeSequence",
]

from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum as BaseStrEnum
from re import RegexFlag
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Final,
    NewType,
    SupportsBytes,
    TypeAlias,
    override,
)

from pydantic import (
    AfterValidator,
    BeforeValidator,
    Field,
    PlainSerializer,
    StringConstraints,
    TypeAdapter,
)
from pydantic_settings import NoDecode

if TYPE_CHECKING:
    from collections.abc import Sequence


type Username = Annotated[
    str,
    StringConstraints(
        pattern=r"[a-zA-Z\-_]+",
        min_length=1,
        max_length=64,
    ),
]


def _validate_password(value: str) -> str:
    bytes = len(value.encode())
    if bytes > 72:
        raise ValueError("password cannot exceed 72 bytes")

    return value


type Password = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(_validate_password),
]


def _validate_email_address(value: str) -> str:
    from email_validator import validate_email

    validated = validate_email(value, check_deliverability=False)
    return validated.normalized.lower()


type EmailAddress = Annotated[
    str,
    AfterValidator(_validate_email_address),
]

BCryptHash: Final = NewType("BCryptHash", str)
_ValidatedBCryptHash = Annotated[
    BCryptHash,
    StringConstraints(pattern=r"^\$2[ayb]\$.{56}$"),
]

if not TYPE_CHECKING:
    BCryptHash = _ValidatedBCryptHash

Argon2Hash: Final = NewType("Argon2Hash", str)
_ValidatedArgon2Hash = Annotated[
    Argon2Hash,
    StringConstraints(
        pattern=r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"
    ),
]

if not TYPE_CHECKING:
    Argon2Hash = _ValidatedArgon2Hash


type PasswordHash = BCryptHash | Argon2Hash


class StrEnum(BaseStrEnum):
    @staticmethod
    @override
    def _generate_next_value_(name: str, *args: Any, **kwargs: Any) -> str:
        return name.lower().replace("_", "-")

    @override
    def __str__(self) -> str:
        return self.value


_order_cache: dict[tuple[type[OrderedStrEnum], str], int] = {}


class OrderedStrEnum(StrEnum):
    @classmethod
    def __order_mapping__(cls) -> dict[Any, int]:
        return {}

    @property
    def order(self) -> int:
        key = (type(self), self)
        value = _order_cache.get(key)
        if value is not None:
            return value

        value = self.__order_mapping__().get(self)
        if value is None:
            value = tuple(type(self)).index(self)

        _order_cache[key] = value
        return value

    @override
    def __lt__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order < __x.order

        return super().__lt__(__x)

    @override
    def __le__(self, __x: str | None) -> bool:
        if __x is None:
            return False

        if isinstance(__x, OrderedStrEnum):
            return self.order <= __x.order

        return super().__le__(__x)

    @override
    def __gt__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order > __x.order

        return super().__gt__(__x)

    @override
    def __ge__(self, __x: str | None) -> bool:
        if __x is None:
            return True

        if isinstance(__x, OrderedStrEnum):
            return self.order >= __x.order

        return super().__ge__(__x)


_REGEX_FLAG_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def _pre_validate_regex_flags(value: object) -> object:
    if not isinstance(value, str):
        return value

    value = value.upper()
    try:
        return RegexFlag[value]
    except KeyError:
        pass

    summed = RegexFlag.NOFLAG
    for character in value:
        try:
            summed |= RegexFlag[character]
        except KeyError:
            raise ValueError(
                f"invalid regex flag character '{character}', must be one of: {_REGEX_FLAG_CHARACTERS}"
            )

    return summed


type RegexFlags = Annotated[RegexFlag, BeforeValidator(_pre_validate_regex_flags)]


if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

    ToBytes: TypeAlias = bytes | bytearray | memoryview | SupportsBytes | ReadableBuffer
    AsBytes: TypeAlias = bytes | bytearray | memoryview | ReadableBuffer
else:
    ToBytes: TypeAlias = bytes | bytearray
    AsBytes: TypeAlias = bytes | bytearray


_NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"
type Name = Annotated[str, StringConstraints(pattern=_NAME_PATTERN)]
type NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
type NonBlankStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]


type Date = date
type Time = time

_DATETIME_OR_DATE_TYPE_ADAPTER: TypeAdapter[datetime | date] = TypeAdapter(
    Annotated[datetime | date, Field(union_mode="left_to_right")]
)


def _pre_validate_datetime(value: object | None) -> object | None:
    if value is None:
        return None

    value = _DATETIME_OR_DATE_TYPE_ADAPTER.validate_python(value)
    # If the value is a date and not a date-time, convert it to a date-time at midnight UTC. Don't
    # change this to `isinstance(value, date)` because `datetime` is a subclass of `date`.
    if not isinstance(value, datetime):
        return datetime(
            value.year,
            value.month,
            value.day,
            tzinfo=UTC,
        )

    # If the value is already timezone-aware and in UTC, return it as is.
    if value.tzinfo is UTC:
        return value
    # If the value is missing timezone information, assume it's UTC.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    # Otherwise, convert the value from its current timezone to UTC.
    return value.astimezone(UTC)


type DateTimeInput = datetime | date | int | float | str
type DateTime = Annotated[datetime, BeforeValidator(_pre_validate_datetime)]

_TIMEDELTA_TYPE_ADAPTER = TypeAdapter(timedelta)


def _pre_validate_timedelta(value: object) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value

    if isinstance(value, str):
        try:
            return _TIMEDELTA_TYPE_ADAPTER.validate_python(value)
        except Exception:
            pass

        from ceres.timing import _parse_sdelta

        return _parse_sdelta(value)

    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    raise ValueError(
        "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
        "'ms', 's', 'm', 'h' or 'd'."
    )


type TimeDeltaInput = timedelta | int | float | str
type TimeDelta = Annotated[timedelta, BeforeValidator(_pre_validate_timedelta)]

_ZERO_TIMEDELTA = timedelta()


def _validate_positive_timedelta(value: timedelta) -> timedelta | None:
    assert value > _ZERO_TIMEDELTA, "must be greater than zero"
    return value


type PositiveTimeDelta = Annotated[TimeDelta, AfterValidator(_validate_positive_timedelta)]


def _validate_non_negative_timedelta(value: timedelta) -> timedelta | None:
    assert value >= _ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return value


type NonNegativeTimeDelta = Annotated[
    TimeDelta,
    AfterValidator(_validate_non_negative_timedelta),
]


def _pre_validate_from_json(value: object) -> object:
    if not isinstance(value, (str, bytes)):
        return value

    try:
        from ceres.data.converters import validate_json

        return validate_json(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid JSON: {exception}")


type FromJSON[T] = Annotated[T, BeforeValidator(_pre_validate_from_json), NoDecode]


def _pre_validate_from_yaml(value: object) -> object:
    if not isinstance(value, (str, bytes)):
        return value

    try:
        from ceres.data.converters import validate_yaml

        return validate_yaml(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid YAML: {exception}")


type FromYAML[T] = Annotated[T, BeforeValidator(_pre_validate_from_yaml), NoDecode]


def _pre_validate_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


def _serialize_number(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


type Number = Annotated[
    int | float,
    Field(union_mode="left_to_right"),
    BeforeValidator(_pre_validate_number),
    PlainSerializer(_serialize_number),
]

type JSONValue = None | bool | Number | str | JSONList | JSONDict
type JSONDict = dict[str, JSONValue]
type JSONList = list[JSONValue]


def _validate_json_serializable(value: object) -> object:
    try:
        from ceres.data.converters import to_json

        to_json(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


type JSONSerializable[T = Any] = Annotated[T, AfterValidator(_validate_json_serializable)]
type JSONSerializableDict[T = Any] = JSONSerializable[dict[str, T]]
type JSONSerializableList[T = Any] = JSONSerializable[list[T]]

type MaybeList[T] = T | list[T]

if TYPE_CHECKING:
    type MaybeSequence[T] = T | Sequence[T]
else:
    type MaybeSequence[T] = T | list[T]
