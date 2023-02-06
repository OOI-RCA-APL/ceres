from datetime import datetime, timezone
from enum import Enum as BaseEnum
from typing import Any

from sqlalchemy import TIMESTAMP, CheckConstraint, Dialect, Enum, Text, TypeDecorator
from sqlalchemy.sql.operators import OperatorType

from ...address import Address
from ..utilities import snakecase


def EnumMapper(cls: type[BaseEnum]) -> Enum:
    enum = Enum(
        *(current.value for current in cls),
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


class AddressMapper(TypeDecorator[Address]):
    impl = Text
    cache_ok = True

    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> Any:
        return self.impl_instance.coerce_compared_value(op, value)

    def process_bind_param(
        self,
        value: Address | None,
        dialect: Dialect,
    ) -> str | None:
        if value is None:
            return None

        return str(value)

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

    def coerce_compared_value(self, op: OperatorType | None, value: Any) -> Any:
        return self.impl_instance.coerce_compared_value(op, value)

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)
