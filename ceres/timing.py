from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter

if TYPE_CHECKING:
    from ceres.data import DateTimeInput, TimeDeltaInput
else:
    DateTimeInput = Any
    TimeDeltaInput = Any

# Per-context override for "now", used to make tests deterministic without monkey-patching the
# stdlib clock.
_now_context_var = ContextVar[datetime | None]("time", default=None)

__all__ = [
    "utc",
    "delta",
    "isodelta",
    "sdelta",
    "set_fake_now",
    "get_fake_now",
]


def utc(value: DateTimeInput | None = None, /) -> datetime:
    """Get the current time in UTC, or convert a date-time-like value to a UTC `datetime`.

    Args:
        value: A `datetime`, ISO 8601 string, or other accepted date-time input. If `None`,
            the current UTC time is returned, honoring any fake-now override set via
            `set_fake_now()`.

    Returns:
        A timezone-aware `datetime` in UTC.
    """
    if value is None:
        fake = get_fake_now()
        if fake is not None:
            return utc(fake)

        return datetime.now(UTC)

    if isinstance(value, datetime):
        if value.tzinfo is UTC:
            return value

        return value.astimezone(UTC)

    from ceres.data import DateTime, validate

    return validate(DateTime, value)


def delta(value: TimeDeltaInput, /) -> timedelta:
    """Convert a time-delta-like value to a `timedelta`.

    Args:
        value: A `timedelta`, number of seconds, ISO 8601 duration string, or other accepted
            time-delta input.

    Returns:
        The equivalent `timedelta`.
    """
    from ceres.data import TimeDelta, validate

    return validate(TimeDelta, value)


_ISO_DELTA_ADAPTER = TypeAdapter(timedelta, config={"ser_json_temporal": "iso8601"})


def isodelta(value: timedelta, /) -> str:
    """Convert a `timedelta` value to an ISO 8601 duration string.

    Args:
        value: The `timedelta` to format.

    Returns:
        An ISO 8601 duration string such as `"PT1H30M"`.

    Raises:
        ValueError: If `value` is not a `timedelta` instance.
    """
    if not isinstance(value, timedelta):
        raise ValueError(f"expected `timedelta` value, got `{type(value)}`")

    # Pydantic emits the duration as a JSON string, strip the surrounding quote characters.
    return _ISO_DELTA_ADAPTER.dump_json(value).decode()[1:-1]


_DELTA_MS = timedelta(milliseconds=1)
_DELTA_S = timedelta(seconds=1)
_DELTA_M = timedelta(minutes=1)
_DELTA_H = timedelta(hours=1)
_DELTA_D = timedelta(days=1)


def sdelta(
    value: timedelta,
    /,
    *,
    decimals: int | None = None,
    space: bool = False,
) -> str:
    """Convert a `timedelta` to a suffixed, human-readable string with an appropriate unit.

    The unit is chosen to fit the magnitude of the duration, ranging from microseconds (`us`)
    up to days (`d`).

    Args:
        value: The `timedelta` to format.
        decimals: Number of digits to display after the decimal point. If `None`, the natural
            string representation of the number is used. Trailing zeros and any trailing decimal
            point are stripped from the result.
        space: Whether to insert a space between the number and the unit.

    Returns:
        A string such as `"500ms"`, `"1.5s"`, or `"2 h"`.

    Raises:
        ValueError: If `value` is not a `timedelta` instance.
    """
    if not isinstance(value, timedelta):
        raise ValueError(f"expected `timedelta` value, got `{type(value)}`")

    if value < _DELTA_MS:
        number, unit = float(value.microseconds), "us"
    elif value < _DELTA_S:
        number, unit = value.microseconds / 1000, "ms"
    elif value < _DELTA_M:
        number, unit = value.total_seconds(), "s"
    elif value < _DELTA_H:
        number, unit = (value / 60).total_seconds(), "m"
    elif value < _DELTA_D:
        number, unit = (value / (60 * 60)).total_seconds(), "h"
    else:
        number, unit = (value / (60 * 60 * 24)).total_seconds(), "d"

    if decimals is not None:
        number_text = f"{number:.{decimals}f}"
    else:
        number_text = f"{number}"

    number_text = number_text.rstrip("0").rstrip(".")

    if space:
        return f"{number_text} {unit}"
    else:
        return f"{number_text}{unit}"


def _get_sdelta_parse_exception() -> ValueError:
    return ValueError(
        "invalid suffixed time-delta value, must be a number with suffix 'us', 'ms', 's', 'm', "
        "'h' or 'd'."
    )


def _parse_sdelta(value: str) -> timedelta:
    if not isinstance(value, str):
        raise _get_sdelta_parse_exception()

    value = value.strip().replace(" ", "").lower()

    # Order matters here, longer suffixes must be checked before shorter ones that are their
    # tail (e.g. `ms` before `s`).
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
        raise _get_sdelta_parse_exception()

    try:
        decoded_value = float(value[: -len(decoded_unit)])
    except Exception:
        raise _get_sdelta_parse_exception() from None

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

    raise _get_sdelta_parse_exception()


def set_fake_now(value: datetime | None) -> None:
    """Set a fake current time for the current thread or async context.

    The value will be returned by `utc()` when called with no arguments. To clear the fake time,
    call this function with `None`.

    This should only ever be used for testing purposes, it should not be used in production code.

    Args:
        value: The fake `datetime` to return, or `None` to clear any previously set value.
    """
    _now_context_var.set(value)


def get_fake_now() -> datetime | None:
    """Get the currently set fake current time for the current thread or async context.

    This should only ever be used for testing purposes, it should not be used in production code.

    Returns:
        The previously configured fake `datetime`, or `None` if no fake-now value is set.
    """
    return _now_context_var.get()
