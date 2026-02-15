from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, TypeAlias, TypedDict, Unpack, override
from uuid import UUID

from sqlalchemy import JSON, ForeignKeyConstraint, PrimaryKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from ceres._internal import util
from ceres._internal.database.types import UUIDMapper
from ceres._internal.entity import (
    BaseEntity,
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityManager,
    BaseEntityQuery,
    BaseEntityRow,
    EntityNaming,
    EntityQuery,
)
from ceres._internal.manager import BaseNodeManager
from ceres._internal.util import MatchMode
from ceres.data import FromYAML, JSONSerializable, MaybeSequence, uuid7
from ceres.user import UserRow

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType


class SettingRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "settings"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper, default_factory=uuid7)
    name: Mapped[str] = mapped_column(Text)
    value: Mapped[JSONSerializable] = mapped_column(JSON)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint("user_id", "name", name=f"pk_{cls.__tablename__}"),
            ForeignKeyConstraint(
                [cls.user_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__user_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )


SettingField: TypeAlias = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "name",
    "value",
]
SettingOrder: TypeAlias = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "name",
    "name:asc",
    "name:desc",
    "value",
    "value:asc",
    "value:desc",
]


class SettingFilterArgs(BaseEntityFilterArgs[SettingField, SettingOrder], total=False):
    user_id: MaybeSequence[UUID] | None
    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None


class SettingFilter(BaseEntityFilter["Setting", SettingField, SettingOrder]):
    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given UUIDs."""
    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given names."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""

    @override
    def _matches(self, obj: Setting) -> bool:
        if not super()._matches(obj):
            return False

        if not util.match_value(obj.user_id, self.user_id):
            return False

        if not util.match_value(obj.name, self.name):
            return False
        if not util.match_string(obj.name, self.name_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.name, self.name_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.name, self.name_suffix, MatchMode.SUFFIX):
            return False

        return True

    @classmethod
    @override
    def _get_row_cls(cls) -> type[SettingRow]:
        return SettingRow

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield columns.user_id.in_(util.seq(self.user_id))

        if self.name is not None:
            yield util.sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield util.sql_match_string(columns.name, self.name_contains, MatchMode.CONTAINS)
        if self.name_prefix is not None:
            yield util.sql_match_string(columns.name, self.name_prefix, MatchMode.PREFIX)
        if self.name_suffix is not None:
            yield util.sql_match_string(columns.name, self.name_suffix, MatchMode.SUFFIX)

    @override
    def _get_default_order(self) -> MaybeSequence[SettingOrder]:
        return "name"


class SettingCreate(BaseEntityCreate, slots=True):
    user_id: UUID
    name: str
    value: FromYAML[JSONSerializable]


class SettingUpdate(TypedDict, total=False):
    name: str
    value: FromYAML[JSONSerializable]


class _BaseSettingQuery(
    BaseEntityQuery[
        "Setting",
        SettingFilter,
        SettingUpdate,
        "SettingQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[SettingQuery]:
        return SettingQuery

    @override
    def where(
        self,
        filter: SettingFilter | None = None,
        **kwargs: Unpack[SettingFilterArgs],
    ) -> SettingQuery:
        return super().where(filter, **kwargs)


class SettingQuery(
    EntityQuery[
        "Setting",
        SettingFilter,
        SettingUpdate,
    ],
    _BaseSettingQuery,
):
    __slots__ = ()


class SettingManager(
    BaseEntityManager[
        "Setting",
        SettingRow,
        SettingCreate,
        SettingUpdate,
        SettingFilter,
        SettingFilterArgs,
    ],
    _BaseSettingQuery,
):
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Setting)

    async def get(self, user_id: UUID, name: str, /) -> Setting | None:
        return await self.where(user_id=user_id, name=name).first()


class BoundSettingManager(SettingManager, BaseNodeManager):
    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)


class Setting(BaseEntity, SettingCreate, slots=True):
    Manager: ClassVar[type[SettingManager]] = SettingManager
    BoundManager: ClassVar[type[BoundSettingManager]] = BoundSettingManager
    Row: ClassVar[type[SettingRow]] = SettingRow
    Create: ClassVar[type[SettingCreate]] = SettingCreate
    Update: ClassVar[type[SettingUpdate]] = SettingUpdate
    Filter: ClassVar[type[SettingFilter]] = SettingFilter
    FilterArgs: ClassVar[type[SettingFilterArgs]] = SettingFilterArgs
    Field = SettingField
    Order = SettingOrder

    __naming__: ClassVar[EntityNaming] = EntityNaming("setting")
