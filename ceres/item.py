from __future__ import annotations

from abc import abstractmethod
from typing import Annotated, Any, ClassVar, Iterable, Mapping, override

from pydantic import Field

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import AddressMapper
from ceres._internal.lazy import lazy_imports
from ceres.address import Address, AddressSelector
from ceres.database.enums import DatabaseType
from ceres.entity import (
    BaseEntity,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityRow,
    BaseEntityUpdate,
)

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, mapped_column
    from sqlalchemy.sql import SQLColumnExpression


class BaseItemRow(BaseEntityRow, kw_only=True):
    __abstract__: ClassVar[bool] = True

    address: Mapped[Address] = mapped_column(AddressMapper, sort_order=-2000)


class BaseItemFilterArgs(BaseEntityFilterArgs, total=False):
    root: Address
    address: AddressSelector | None


class BaseItemFilter[_ItemT: BaseItem](BaseEntityFilter[_ItemT]):
    address: Annotated[AddressSelector | None, CLIOption(str | None)] = Field(
        default=None,
        description="Filter by associated address.",
    )
    root: Annotated[Address, CLIOption(str | None)] = Field(
        default=Address.ROOT,
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

    @classmethod
    @abstractmethod
    @override
    def _get_row_cls(cls) -> type[BaseItemRow]: ...

    @override
    def _get_search_content(self, obj: _ItemT) -> Mapping[str, str]:
        return {
            **super()._get_search_content(obj),
            "address": str(obj.address),
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> Mapping[str, SQLColumnExpression[Any]]:
        columns = self._get_row_cls()

        return {
            **super()._get_database_search_content(dialect),
            "address": columns.address,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.address is not None:
            yield self.address.matches_expression(columns.address, self.root)


class BaseItemCreate(BaseEntity):
    address: Annotated[Address, CLIOption(str)]


class BaseItemUpdate(BaseEntityUpdate, total=False):
    address: Address


class BaseItem(BaseItemCreate):
    Row: ClassVar[type[BaseItemRow]] = BaseItemRow
    Create: ClassVar[type[BaseItemCreate]] = BaseItemCreate
    Update: ClassVar[type[BaseItemUpdate]] = BaseItemUpdate
    Filter: ClassVar[type[BaseItemFilter[BaseItem]]] = BaseItemFilter
    FilterArgs: ClassVar[type[BaseItemFilterArgs]] = BaseItemFilterArgs
