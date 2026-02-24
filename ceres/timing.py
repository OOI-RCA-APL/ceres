from contextvars import ContextVar
from datetime import UTC, datetime

_now_context_var = ContextVar[datetime | None]("time", default=None)


def utc(value: datetime | int | float | str | None = None, /) -> datetime:
    if value is None:
        fake = _now_context_var.get()
        if fake is not None:
            return utc(fake)

        return datetime.now(UTC)

    if isinstance(value, datetime):
        if value.tzinfo is UTC:
            return value

        return value.astimezone(UTC)

    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, UTC)

    if isinstance(value, str):
        return datetime.fromisoformat(value).astimezone(UTC)

    raise TypeError(f"expected `datetime`, `int`, `float`, `str` or `None`, got {type(value)}")
