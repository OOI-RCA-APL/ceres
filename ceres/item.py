from abc import abstractmethod
from typing import Annotated, ClassVar, Iterable, TypeVar

from pydantic import Field
from sqlalchemy import ColumnExpressionArgument, Index
from sqlalchemy.orm import Mapped, QueryableAttribute, mapped_column
from sqlalchemy.schema import SchemaItem
from typing_extensions import override

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import AddressMapper
from ceres._internal.utilities import as_sequence
from ceres.address import Address, AddressSelector
from ceres.database.enums import DatabaseType
from ceres.entity import (
    BaseEntity,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityRow,
    BaseEntityUpdate,
)


class BaseItemRow(BaseEntityRow, kw_only=True):
    __abstract__ = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            Index(f"ix_{cls.__tablename__}__address", "address"),
        )


_ItemT = TypeVar("_ItemT", bound="BaseItem")


class BaseItemFilterArgs(BaseEntityFilterArgs, total=False):
    root: Address
    address: AddressSelector | None


class BaseItemFilter(BaseEntityFilter[_ItemT]):
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by associated address.",
    )
    root: Annotated[Address, CLIOption(str | None)] = Field(
        default=Address.root(),
        description="The root address relative `address` selectors are mapped to.",
    )

    @override
    def matches(self, obj: _ItemT) -> bool:  # type: ignore
        if not super().matches(obj):
            return False

        if self.address is not None:
            if not self.address.matches(obj.address, self.root):
                return False

        return True

    @abstractmethod
    @override
    def _get_row_cls(self) -> type[BaseItemRow]: ...

    @override
    def _get_search_content(self, obj: _ItemT) -> dict[str, str]:
        return {
            "address": obj.address,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_row_cls()

        return {
            "address": columns.address,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.id is not None:
            yield columns.id.in_(as_sequence(self.id))
        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)


class BaseItemCreate(BaseEntity):
    address: Annotated[Address, CLIOption(str)]


class BaseItemUpdate(BaseEntityUpdate, total=False):
    address: Address


class BaseItem(BaseItemCreate):
    Row: ClassVar = BaseItemRow
    Create: ClassVar = BaseItemCreate
    Update: ClassVar = BaseItemUpdate
    Filter: ClassVar = BaseItemFilter
    FilterArgs: ClassVar = BaseItemFilterArgs
