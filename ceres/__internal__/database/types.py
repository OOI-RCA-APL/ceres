from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, override
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, Dialect, Enum, Text, TypeDecorator, Uuid

from ceres.__internal__.utilities.case import snakecase
from ceres.address import Address

if TYPE_CHECKING:
    from enum import Enum as BaseEnum

    from sqlalchemy.orm import InstrumentedAttribute
    from sqlalchemy.sql.operators import OperatorType


def EnumMapper(cls: type[BaseEnum]) -> Enum:
    """Create a SQLAlchemy ``Enum`` type for the given Python enum class.

    Configure the column type to use enum values (not names), disable native database enum types,
    and derive the column type name from the enum class name in snake_case.

    Args:
        cls: The Python enum class to map.

    Returns:
        A SQLAlchemy ``Enum`` type configured for the given enum class.
    """
    enum = Enum(
        cls,
        values_callable=lambda enum: [current.value for current in enum],
        native_enum=False,
        create_constraint=False,
        name=snakecase(cls.__name__),
    )

    enum.length = None
    return enum


def EnumConstraint(
    column: InstrumentedAttribute[Any],
    cls: type[BaseEnum],
    name: str,
) -> CheckConstraint:
    """Create a ``CheckConstraint`` that restricts a column's values to the members of an enum.

    Args:
        column: The mapped column attribute to constrain.
        cls: The Python enum class whose members define the allowed values.
        name: The name of the constraint in the database schema.

    Returns:
        A ``CheckConstraint`` that validates the column value is a member of the given enum.
    """
    return CheckConstraint(column.in_(cls), name=name)


class UUIDMapper(TypeDecorator[UUID]):
    """SQLAlchemy type decorator that map UUID values between Python and the database.

    Use native UUID support when the dialect provides it, and fall back to a dash-formatted string
    representation otherwise. Normalize subclasses of ``UUID`` (such as asyncpg's protocol UUID)
    to standard ``uuid.UUID`` instances on result processing.
    """

    impl = Uuid
    cache_ok = True

    if TYPE_CHECKING:
        impl_instance: Uuid

    def __init__(self) -> None:
        """Initialize the UUID mapper with native UUID support enabled."""
        super().__init__(
            as_uuid=True,
            native_uuid=True,
        )

    @override
    def bind_processor(self, dialect: Dialect) -> Callable[..., str | None]:
        """Return a callable that convert a UUID to the format expected by the dialect.

        Delegate to the default processor for dialects with native UUID support. For other
        dialects, return a processor that formats UUIDs as dash-separated strings.

        Args:
            dialect: The SQLAlchemy dialect in use.

        Returns:
            A callable that accept a UUID or string and return a formatted string, or None.
        """
        if dialect.supports_native_uuid:
            return super().bind_processor(dialect)  # type: ignore

        # Reformat to keep dashes.
        def process(value: UUID | str | None):
            if value is None:
                return None
            if isinstance(value, str):
                return str(UUID(value))

            return str(value)

        return process

    @override
    def result_processor(self, dialect: Dialect, coltype: Any) -> Callable[..., UUID | None]:
        """Return a callable that convert a database result into a standard ``uuid.UUID``.

        For native UUID dialects, normalize driver-specific UUID subclasses to ``uuid.UUID``. For
        non-native dialects, parse the string value into a ``uuid.UUID``.

        Args:
            dialect: The SQLAlchemy dialect in use.
            coltype: The column type reported by the database driver.

        Returns:
            A callable that accept a raw result value and return a ``uuid.UUID`` or None.
        """

        def process_native(value: UUID | None) -> UUID | None:
            if value is None:
                return None

            # Convert subclasses of UUID, such as `asyncpg.pgproto.pgproto.UUID`, to normal UUIDs.
            return UUID(int=value.int)

        def process_non_native(value: str | None) -> UUID | None:
            if value is None:
                return None

            return UUID(value)

        if dialect.supports_native_uuid:
            return process_native

        return process_non_native

    @override
    def process_result_value(self, value: object, dialect: Dialect) -> UUID | None:
        """Convert a single result value to a ``uuid.UUID``.

        Handle None, UUID instances, and string representations. Raise ``NotImplementedError``
        for any other type.

        Args:
            value: The raw value from the database driver.
            dialect: The SQLAlchemy dialect in use.

        Returns:
            A standard ``uuid.UUID``, or None if the value is None.

        Raises:
            NotImplementedError: If the value is not None, a UUID, or a string.
        """
        if value is None:
            return None
        if isinstance(value, UUID):
            return UUID(int=value.int)
        if isinstance(value, str):
            return UUID(value)

        raise NotImplementedError(f"Received invalid UUID value from driver: {value!r}")


class AddressMapper(TypeDecorator[Address]):
    """SQLAlchemy type decorator that map ``Address`` values to and from text columns."""

    impl = Text
    cache_ok = True

    @override
    def process_bind_param(
        self,
        value: str | Address | None,
        dialect: Dialect,
    ) -> str | None:
        """Convert an ``Address`` or string to its string representation for storage.

        Args:
            value: The address value to bind, or None.
            dialect: The SQLAlchemy dialect in use.

        Returns:
            The string form of the address, or None if the value is None.
        """
        if value is None:
            return None

        return str(value)

    @override
    def process_result_value(
        self,
        value: str | Address | None,
        dialect: Dialect,
    ) -> Address | None:
        """Convert a stored string back into an ``Address`` instance.

        Args:
            value: The raw value from the database, or None.
            dialect: The SQLAlchemy dialect in use.

        Returns:
            An ``Address`` instance, or None if the value is None.
        """
        if value is None:
            return None

        return Address(value)


class DateTimeMapper(TypeDecorator[datetime]):
    """SQLAlchemy type decorator that normalize datetime values to UTC on both bind and result.

    Store all datetime values as timezone-aware UTC timestamps. Naive datetimes are assumed to be
    UTC and annotated accordingly, while timezone-aware datetimes are converted to UTC.
    """

    impl = TIMESTAMP
    cache_ok = True

    def __init__(self) -> None:
        """Initialize the datetime mapper with timezone support enabled."""
        super().__init__(timezone=True)

    @override
    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> Any:
        """Delegate comparison coercion to the underlying ``TIMESTAMP`` implementation.

        Args:
            op: The comparison operator, or None.
            value: The value being compared against.

        Returns:
            The coerced type from the underlying implementation.
        """
        return self.impl_instance.coerce_compared_value(op, value)

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Normalize a datetime to UTC before binding it as a query parameter.

        Args:
            value: The datetime to bind, or None.
            dialect: The SQLAlchemy dialect in use.

        Returns:
            A UTC datetime, or None if the value is None.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Normalize a datetime from the database to UTC.

        Args:
            value: The datetime from the database result, or None.
            dialect: The SQLAlchemy dialect in use.

        Returns:
            A UTC datetime, or None if the value is None.
        """
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)
