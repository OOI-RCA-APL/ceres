from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone

_now_context_var = ContextVar[datetime | None]("time", default=None)


def utc(value: datetime | int | float | str | None = None, /) -> datetime:
    if value is None:
        fake = _now_context_var.get()
        if fake is not None:
            return utc(fake)

        return datetime.now(timezone.utc)

    if isinstance(value, datetime):
        if value.tzinfo is timezone.utc:
            return value

        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)

    if isinstance(value, str):
        return datetime.fromisoformat(value).astimezone(timezone.utc)

    raise TypeError(f"expected `datetime`, `int`, `float`, `str` or `None`, got {type(value)}")
