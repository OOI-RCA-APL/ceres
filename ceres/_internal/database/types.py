from datetime import datetime, timezone
from enum import Enum as BaseEnum
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import TIMESTAMP, CheckConstraint, Dialect, Enum, Text, TypeDecorator, Uuid
from sqlalchemy.sql.operators import OperatorType
from typing_extensions import override

from ceres._internal.utilities import snakecase
from ceres.address import Address


def EnumMapper(cls: type[BaseEnum]) -> Enum:
    enum = Enum(
        cls,
        values_callable=lambda enum: [current.value for current in enum],
        native_enum=False,
        create_constraint=False,
        name=snakecase(cls.__name__),
    )

    enum.length = None
    return enum


def EnumConstraint(column: str, cls: type[BaseEnum], name: str) -> CheckConstraint:
    return CheckConstraint(
        sqltext=f"{column} in ({', '.join([repr(enum.value) for enum in cls])})",
        name=name,
    )


class UUIDMapper(Uuid[UUID]):
    @override
    def bind_processor(self, dialect: Dialect) -> Callable[..., str | None]:
        if dialect.supports_native_uuid and self.native_uuid:
            return super().bind_processor(dialect)  # type: ignore

        # Reformat to keep dashes.
        def process(value: UUID | str | None):
            if value is None:
                return None
            if isinstance(value, str):
                return str(UUID(value))

            return str(value)

        return process


class AddressMapper(TypeDecorator[Address]):
    impl = Text
    cache_ok = True

    @override
    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> Any:
        return self.impl_instance.coerce_compared_value(op, value)

    @override
    def process_bind_param(
        self,
        value: Address | None,
        dialect: Dialect,
    ) -> str | None:
        if value is None:
            return None

        return str(value)

    @override
    def process_result_value(
        self,
        value: Address | None,
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
