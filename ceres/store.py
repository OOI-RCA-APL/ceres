from typing import ClassVar

from sqlalchemy import Boolean, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import SchemaItem
from sqlalchemy.sql import expression
from typing_extensions import override

from ceres._internal.database.types import AddressMapper
from ceres.address import Address
from ceres.entity import BaseEntity, BaseEntityRow


class StoreRow(BaseEntityRow, kw_only=True):
    __tablename__ = "stores"

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
    Row: ClassVar = StoreRow

    address: Address
    enabled: bool = False
