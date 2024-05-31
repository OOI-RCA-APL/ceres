from __future__ import annotations

from datetime import datetime, timezone


def utc() -> datetime:
    return datetime.now(timezone.utc)
