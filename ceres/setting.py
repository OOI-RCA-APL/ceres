from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override
from uuid import UUID

from sqlalchemy import JSON, ForeignKeyConstraint, PrimaryKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import UUIDMapper
from ceres.__internal__.entity import (
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityManager,
    BaseEntityQuery,
    BaseEntityRow,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.utilities.collections import seq
from ceres.data import FromYAML, JSONSerializable, MaybeSequence, uuid7
from ceres.user import UserRow

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType

__all__ = [
    "Setting",
    "SettingField",
    "SettingOrder",
    "SettingFilterArgs",
    "SettingFilter",
    "SettingCreate",
    "SettingUpdate",
    "SettingManager",
    "BoundSettingManager",
]


class SettingRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `Setting` entity."""

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


type SettingField = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "name",
    "value",
]
"""Field names selectable in `Setting` queries."""

type SettingOrder = Literal[
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
"""Ordering keys accepted by `Setting` queries."""


class SettingFilterArgs(BaseEntityFilterArgs[SettingField, SettingOrder], total=False):
    """Keyword-argument form of `SettingFilter` for ergonomic call sites."""

    user_id: MaybeSequence[UUID] | None
    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None


class SettingFilter(BaseEntityFilter["Setting", SettingField, SettingOrder]):
    """Filter for selecting `Setting` records by owning user or name."""

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

        if not self._match_value(obj.user_id, self.user_id):
            return False

        if not self._match_value(obj.name, self.name):
            return False
        if not self._match_string_contains(obj.name, self.name_contains):
            return False
        if not self._match_string_prefix(obj.name, self.name_prefix):
            return False
        if not self._match_string_suffix(obj.name, self.name_suffix):
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
            yield columns.user_id.in_(seq(self.user_id))

        if self.name is not None:
            yield self._sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield self._sql_match_string_contains(columns.name, self.name_contains)
        if self.name_prefix is not None:
            yield self._sql_match_string_prefix(columns.name, self.name_prefix)
        if self.name_suffix is not None:
            yield self._sql_match_string_suffix(columns.name, self.name_suffix)

    @override
    def _get_default_order(self) -> MaybeSequence[SettingOrder]:
        return "name"


class SettingCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `Setting` record."""

    user_id: UUID
    """Identifier of the user that owns this setting."""
    name: str
    """Name of the setting, unique per user."""
    value: FromYAML[JSONSerializable]
    """Arbitrary JSON-serializable value stored for this setting."""


class SettingUpdate(TypedDict, total=False):
    """Partial update for an existing `Setting` record."""

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
    def where(  # type: ignore
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
    """Query builder for `Setting` records."""

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
    """Database-bound manager for `Setting` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Setting)

    async def get(self, user_id: UUID, name: str, /) -> Setting | None:
        """Fetch a single setting by its composite key.

        Args:
            user_id: Identifier of the user that owns the setting.
            name: Name of the setting.

        Returns:
            The matching setting, or `None` if no setting with that key exists.
        """
        return await self.where(user_id=user_id, name=name).first()


class BoundSettingManager(SettingManager, BaseNodeManager):
    """Component-bound setting manager exposed to nodes."""

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)


class Setting(SettingCreate, ConcreteEntity[SettingRow], slots=True):
    """Per-user named value used to persist user preferences and application state.

    Settings are keyed by `(user_id, name)` and store arbitrary JSON-serializable values.
    """

    Manager = SettingManager
    BoundManager = BoundSettingManager
    Create = SettingCreate
    Update = SettingUpdate
    Filter = SettingFilter
    FilterArgs = SettingFilterArgs
    Field = SettingField
    Order = SettingOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("setting")
