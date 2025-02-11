from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, ClassVar, Iterable, Literal, TypeAlias, override

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import Index, SchemaItem
from sqlalchemy.sql import SQLColumnExpression

from ceres._internal.database.types import AddressMapper
from ceres._internal.entity import (
    BaseEntity,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityRow,
    BaseEntityUpdate,
)
from ceres.address import Address, AddressSelector
from ceres.database import DatabaseType


class BaseItemRow(BaseEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__address", cls.address),
        )


BaseItemField: TypeAlias = Literal["address"]
BaseItemOrder: TypeAlias = Literal[
    "address",
    "address:asc",
    "address:desc",
]


class BaseItemFilterArgs[
    FieldT: str,
    OrderT: str,
](BaseEntityFilterArgs[FieldT, OrderT], total=False):
    root: Address
    address: AddressSelector | None


class BaseItemFilter[
    ItemT: BaseItem,
    FieldT: str,
    OrderT: str,
](BaseEntityFilter[ItemT, FieldT, OrderT]):
    address: AddressSelector | None = None
    """Filter by `address` matching one or more address selectors."""
    root: Address = Address.ROOT
    """The address which relative address selectors in `address` are relative to."""

    @override
    def matches(self, obj: ItemT) -> bool:
        if not super().matches(obj):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False

        return True

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseItemRow]: ...

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)


class BaseItemCreate(BaseEntity):
    address: Address


class BaseItemUpdate(BaseEntityUpdate, total=False):
    address: Address


class BaseItem(BaseItemCreate):
    Row: ClassVar[type[BaseItemRow]] = BaseItemRow
    Create: ClassVar[type[BaseItemCreate]] = BaseItemCreate
    Update: ClassVar[type[BaseItemUpdate]] = BaseItemUpdate

    if TYPE_CHECKING:
        Filter: ClassVar = BaseItemFilter
        FilterArgs: ClassVar = BaseItemFilterArgs
        Field: ClassVar = BaseItemField
        Order: ClassVar = BaseItemOrder
    else:
        Filter: ClassVar[type[BaseItemFilter]] = BaseItemFilter
        FilterArgs: ClassVar[type[BaseItemFilterArgs]] = BaseItemFilterArgs
        Field: ClassVar[type[BaseItemField]] = BaseItemField
        Order: ClassVar[type[BaseItemOrder]] = BaseItemOrder
