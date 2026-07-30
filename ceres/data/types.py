"""Helper types, type aliases, enums, and validators.

Provides reusable Pydantic-compatible type aliases for common values like usernames, passwords,
date-times, and JSON-shaped data, along with custom enum bases and a flexible `Number` type that
auto-narrows integer-valued floats.
"""

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
"""Account username, restricted to letters, hyphens, and underscores, between 1 and 64 chars."""


def _validate_password(value: str) -> str:
    # bcrypt has a hard 72-byte input limit, validate against the encoded byte length rather than
    # character count to handle multi-byte characters correctly.
    byte_count = len(value.encode())
    if byte_count > 72:
        raise ValueError("password cannot exceed 72 bytes")

    return value


type Password = Annotated[
    str,
    StringConstraints(min_length=1, max_length=32),
    AfterValidator(_validate_password),
]
"""User-supplied password, constrained to bcrypt's effective input limits."""


def _validate_email_address(value: str) -> str:
    from email_validator import validate_email

    # Skip deliverability checks because they require DNS lookups which are slow and would make
    # validation depend on network availability.
    validated = validate_email(value, check_deliverability=False)
    return validated.normalized.lower()


type EmailAddress = Annotated[
    str,
    AfterValidator(_validate_email_address),
]
"""RFC-compliant email address, normalized and lowercased on validation."""

BCryptHash: Final = NewType("BCryptHash", str)
"""A bcrypt password hash string, distinct from a plain `str` for type safety."""

_ValidatedBCryptHash = Annotated[
    BCryptHash,
    StringConstraints(pattern=r"^\$2[ayb]\$.{56}$"),
]

if not TYPE_CHECKING:
    # At runtime, replace `BCryptHash` with the validated alias so Pydantic enforces the format,
    # while static checkers see the plain `NewType` for clearer error messages.
    BCryptHash = _ValidatedBCryptHash

Argon2Hash: Final = NewType("Argon2Hash", str)
"""An Argon2 password hash string, distinct from a plain `str` for type safety."""

_ValidatedArgon2Hash = Annotated[
    Argon2Hash,
    StringConstraints(
        pattern=r"^\$argon2(?:(?:id)|i|d)\$v=\d+\$m=\d+,t=\d+,p=\d+\$[A-Za-z0-9+/$]+$"
    ),
]

if not TYPE_CHECKING:
    Argon2Hash = _ValidatedArgon2Hash


type PasswordHash = BCryptHash | Argon2Hash
"""Either a bcrypt or Argon2 password hash, supporting either algorithm interchangeably."""


class StrEnum(BaseStrEnum):
    """String enum whose auto-generated values are kebab-cased lowercase forms of member names.

    For example, a member named `MY_VALUE` automatically gets the value `"my-value"` when declared
    via `auto()`. Stringifying a member returns its value rather than the standard `EnumName.MEMBER`
    form.
    """

    @staticmethod
    @override
    def _generate_next_value_(name: str, *args: Any, **kwargs: Any) -> str:
        return name.lower().replace("_", "-")

    @override
    def __str__(self) -> str:
        return self.value


# Cache resolved order values per (enum class, member) so repeated comparisons stay cheap.
_order_cache: dict[tuple[type[OrderedStrEnum], str], int] = {}


class OrderedStrEnum(StrEnum):
    """String enum whose members support relative comparisons via an explicit ordering.

    Subclasses may override `__order_mapping__` to supply explicit ordering. When a member is not
    listed in that mapping, its declaration order in the class body is used as a fallback.
    Comparisons against `None` follow the convention that any member is considered greater than
    `None`.
    """

    @classmethod
    def __order_mapping__(cls) -> dict[Any, int]:
        """Return a mapping from enum members to their sort order.

        Override this in subclasses to customize ordering. The default implementation returns an
        empty dict, causing all members to fall back to declaration order.
        """
        return {}

    @property
    def order(self) -> int:
        """Resolved sort order for this member, cached after the first lookup."""
        key = (type(self), self)
        value = _order_cache.get(key)
        if value is not None:
            return value

        value = self.__order_mapping__().get(self)
        if value is None:
            # Fall back to the member's declaration order in the class body.
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


# Single-character flag aliases like `I`, `M`, `S`, etc, used for compact regex flag specifications.
_REGEX_FLAG_CHARACTERS = set(member for member in RegexFlag.__members__ if len(member) == 1)


def _pre_validate_regex_flags(value: object) -> object:
    if not isinstance(value, str):
        return value

    value = value.upper()
    try:
        # First try to match the entire string as a single named flag (e.g. `"IGNORECASE"`).
        return RegexFlag[value]
    except KeyError:
        pass

    # Otherwise treat the string as a sequence of single-character flag aliases and OR them
    # together (e.g. `"IM"` becomes `IGNORECASE | MULTILINE`).
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
"""`re.RegexFlag` value that also accepts string forms like `"IGNORECASE"` or `"IM"`."""


if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

    ToBytes: TypeAlias = bytes | bytearray | memoryview | SupportsBytes | ReadableBuffer
    AsBytes: TypeAlias = bytes | bytearray | memoryview | ReadableBuffer
else:
    ToBytes: TypeAlias = bytes | bytearray
    AsBytes: TypeAlias = bytes | bytearray


_NAME_PATTERN = r"^[a-zA-Z_\-][a-zA-Z0-9_\-]*$"

type Name = Annotated[str, StringConstraints(pattern=_NAME_PATTERN)]
"""Identifier-like string starting with a letter, underscore, or hyphen."""

type NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
"""String containing at least one character."""

type NonBlankStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
"""String containing at least one non-whitespace character."""


type Date = date
type Time = time

# A union with `union_mode="left_to_right"` ensures Pydantic prefers `datetime` parsing first, only
# falling back to `date` if the input cannot be parsed as a date-time.
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

    if value.tzinfo is UTC:
        return value
    # If the value is missing timezone information, assume it's UTC rather than raising. This
    # matches the historical behavior of treating naive timestamps as UTC across the codebase.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    # Otherwise, convert the value from its current timezone to UTC.
    return value.astimezone(UTC)


type DateTimeInput = datetime | date | int | float | str
"""Any value that can be coerced into a `DateTime`, useful as an input parameter type."""

type DateTime = Annotated[datetime, BeforeValidator(_pre_validate_datetime)]
"""Timezone-aware `datetime` normalized to UTC, accepting dates, timestamps, and ISO strings."""

_TIMEDELTA_TYPE_ADAPTER = TypeAdapter(timedelta)


def _pre_validate_timedelta(value: object) -> timedelta | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value

    if isinstance(value, str):
        try:
            # Try the standard ISO-8601 interval format first.
            return _TIMEDELTA_TYPE_ADAPTER.validate_python(value)
        except Exception:
            pass

        # A bare number reads as seconds, like a numeric value would.
        try:
            return timedelta(seconds=float(value))
        except Exception:
            pass

        # Fall back to the project's custom suffix format (`5s`, `100ms`, etc.).
        from ceres.timing import _parse_sdelta

        return _parse_sdelta(value)

    if isinstance(value, (int, float)):
        return timedelta(seconds=value)

    raise ValueError(
        "invalid timedelta value, must be a ISO formatted interval or number with suffix 'us', "
        "'ms', 's', 'm', 'h' or 'd'."
    )


type TimeDeltaInput = timedelta | int | float | str
"""Any value that can be coerced into a `TimeDelta`."""

type TimeDelta = Annotated[timedelta, BeforeValidator(_pre_validate_timedelta)]
"""`timedelta` accepting ISO-8601 intervals, numeric seconds, or suffixed strings like `"5s"`."""

_ZERO_TIMEDELTA = timedelta()


def _validate_positive_timedelta(value: timedelta) -> timedelta | None:
    assert value > _ZERO_TIMEDELTA, "must be greater than zero"
    return value


type PositiveTimeDelta = Annotated[TimeDelta, AfterValidator(_validate_positive_timedelta)]
"""`TimeDelta` constrained to strictly positive durations."""


def _validate_non_negative_timedelta(value: timedelta) -> timedelta | None:
    assert value >= _ZERO_TIMEDELTA, "must be greater than or equal to zero"
    return value


type NonNegativeTimeDelta = Annotated[
    TimeDelta,
    AfterValidator(_validate_non_negative_timedelta),
]
"""`TimeDelta` constrained to zero or positive durations."""


def _pre_validate_from_json(value: object) -> object:
    if not isinstance(value, (str, bytes)):
        return value

    try:
        from ceres.data.converters import validate_json

        return validate_json(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid JSON: {exception}")


type FromJSON[T] = Annotated[T, BeforeValidator(_pre_validate_from_json), NoDecode]
"""Type wrapper that parses incoming `str`/`bytes` as JSON before validating against `T`."""


def _pre_validate_from_yaml(value: object) -> object:
    if not isinstance(value, (str, bytes)):
        return value

    try:
        from ceres.data.converters import validate_yaml

        return validate_yaml(Any, value)
    except Exception as exception:
        raise ValueError(f"invalid YAML: {exception}")


type FromYAML[T] = Annotated[T, BeforeValidator(_pre_validate_from_yaml), NoDecode]
"""Type wrapper that parses incoming `str`/`bytes` as YAML before validating against `T`."""


def _pre_validate_number(value: object) -> object:
    # Narrow integer-valued floats to `int` so that `1.0` and `1` validate to the same type. This
    # matters for the `int | float` union below, which would otherwise always pick `float`.
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


def _serialize_number(value: object) -> object:
    # Mirror the validator on the way out so round-trips preserve the integer narrowing.
    if isinstance(value, float) and value.is_integer():
        return int(value)

    return value


type Number = Annotated[
    int | float,
    Field(union_mode="left_to_right"),
    BeforeValidator(_pre_validate_number),
    PlainSerializer(_serialize_number),
]
"""Numeric value that prefers `int` when the value is integer-valued, falling back to `float`."""

type JSONValue = None | bool | Number | str | JSONList | JSONDict
"""Any value representable in JSON."""

type JSONDict = dict[str, JSONValue]
"""JSON object with string keys and `JSONValue` values."""

type JSONList = list[JSONValue]
"""JSON array of `JSONValue` items."""


def _validate_json_serializable(value: object) -> object:
    try:
        from ceres.data.converters import to_json

        # Probe the value by attempting a full JSON serialization, the result is discarded since we
        # only care about whether the operation succeeds.
        to_json(value)
    except Exception as error:
        raise ValueError(f"not serializable to JSON: {error}")

    return value


type JSONSerializable[T = Any] = Annotated[T, AfterValidator(_validate_json_serializable)]
"""Type wrapper that asserts a value can be serialized to JSON via `to_json`."""

type JSONSerializableDict[T = Any] = JSONSerializable[dict[str, T]]
"""Dict whose values are JSON-serializable."""

type JSONSerializableList[T = Any] = JSONSerializable[list[T]]
"""List whose items are JSON-serializable."""

type MaybeList[T] = T | list[T]
"""Either a single `T` or a list of `T`s, useful for fields that accept either form."""

if TYPE_CHECKING:
    type MaybeSequence[T] = T | Sequence[T]
else:
    # At runtime, narrow `Sequence` to `list` because Pydantic cannot validate against the abstract
    # `Sequence` protocol without additional configuration.
    type MaybeSequence[T] = T | list[T]
