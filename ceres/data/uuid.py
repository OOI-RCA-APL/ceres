"""UUID generation utilities.

Prefer the `uuid_utils` package when available because its native implementation is significantly
faster than the standard library, falling back to `uuid.uuid4` if it is not installed.
"""

from __future__ import annotations

from uuid import UUID

__all__ = [
    "uuid4",
    "uuid7",
]


def uuid4() -> UUID:
    """Generate a random version 4 UUID.

    Returns:
        A new random UUID, using `uuid_utils.uuid4` when available for speed and falling back to
        `uuid.uuid4` from the standard library otherwise.
    """
    try:
        from uuid_utils import uuid4

        # `uuid_utils` returns its own `UUID` type, convert it to the standard library type so the
        # return value is interchangeable with `uuid.UUID` instances.
        return UUID(int=uuid4().int)
    except ImportError:
        from uuid import uuid4

        return uuid4()


def uuid7(
    timestamp: int | None = None,
    nanoseconds: int | None = None,
) -> UUID:
    """Generate a version 7 UUID using a time value and random bytes.

    Version 7 UUIDs encode a Unix timestamp in their high-order bits, making them sortable by
    creation time which is useful as database primary keys.

    Args:
        timestamp: Optional Unix timestamp in seconds to encode into the UUID. Uses the current
            time when `None`.
        nanoseconds: Optional sub-second precision in nanoseconds. Uses zero when `None`.

    Returns:
        A new version 7 UUID as a standard-library `UUID` instance.

    Raises:
        ImportError: If the `uuid_utils` package is not installed, since the standard library does
            not yet provide a version 7 implementation.
    """
    from uuid_utils import uuid7

    return UUID(int=uuid7(timestamp, nanoseconds).int)
