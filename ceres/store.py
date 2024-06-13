from __future__ import annotations

from typing import ClassVar, override

from ceres._internal.database.types import AddressMapper
from ceres._internal.lazy import lazy_imports
from ceres.address import Address
from ceres.entity import BaseEntity, BaseEntityRow

with lazy_imports(__name__):
    from sqlalchemy import Boolean, UniqueConstraint
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.schema import SchemaItem
    from sqlalchemy.sql import expression


class StoreRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "stores"

    address: Mapped[Address] = mapped_column(AddressMapper)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=expression.false())

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            UniqueConstraint("address", name=f"uq_{cls.__tablename__}"),
        )


class Store(BaseEntity):
    Row: ClassVar[type[StoreRow]] = StoreRow

    address: Address
    enabled: bool = False
