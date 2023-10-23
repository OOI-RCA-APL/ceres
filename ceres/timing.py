from datetime import datetime, timezone


def utc() -> datetime:
    return datetime.now(timezone.utc)
