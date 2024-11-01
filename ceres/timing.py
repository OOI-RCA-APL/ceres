from __future__ import annotations

from datetime import datetime, timezone


def utc(value: datetime | int | float | str | None = None, /) -> datetime:
    if value is None:
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
