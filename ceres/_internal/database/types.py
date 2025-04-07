from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as BaseEnum
from typing import TYPE_CHECKING, Any, Callable, override
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, Dialect, Enum, Text, TypeDecorator, Uuid
from sqlalchemy.sql.operators import OperatorType

from ceres._internal import util
from ceres.address import Address


def EnumMapper(cls: type[BaseEnum]) -> Enum:
    enum = Enum(
        cls,
        values_callable=lambda enum: [current.value for current in enum],
        native_enum=False,
        create_constraint=False,
        name=util.snakecase(cls.__name__),
    )

    enum.length = None
    return enum


def EnumConstraint(column: str, cls: type[BaseEnum], name: str) -> CheckConstraint:
    return CheckConstraint(
        sqltext=f"{column} in ({', '.join([repr(enum.value) for enum in cls])})",
        name=name,
    )


class UUIDMapper(TypeDecorator[UUID]):
    impl = Uuid
    cache_ok = True

    if TYPE_CHECKING:
        impl_instance: Uuid

    def __init__(self) -> None:
        super().__init__(
            as_uuid=True,
            native_uuid=True,
        )

    @override
    def bind_processor(self, dialect: Dialect) -> Callable[..., str | None]:
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
        if value is None:
            return None
        if isinstance(value, UUID):
            return UUID(int=value.int)
        if isinstance(value, str):
            return UUID(value)

        raise NotImplementedError(f"Received invalid UUID value from driver: {value!r}")


class AddressMapper(TypeDecorator[Address]):
    impl = Text
    cache_ok = True

    @override
    def process_bind_param(
        self,
        value: str | Address | None,
        dialect: Dialect,
    ) -> str | None:
        if value is None:
            return None

        return str(value)

    @override
    def process_result_value(
        self,
        value: str | Address | None,
        dialect: Dialect,
    ) -> Address | None:
        if value is None:
            return None

        return Address(value)


class DateTimeMapper(TypeDecorator[datetime]):
    impl = TIMESTAMP
    cache_ok = True

    def __init__(self) -> None:
        super().__init__(timezone=True)

    @override
    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> Any:
        return self.impl_instance.coerce_compared_value(op, value)

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)
