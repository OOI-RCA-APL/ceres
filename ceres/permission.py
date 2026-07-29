from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import EnumConstraint, EnumMapper, TextMapper, UUIDMapper
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
from ceres.config import ComponentAccessLevel
from ceres.data import MaybeSequence, StrEnum
from ceres.group import GroupRow
from ceres.user import UserRow

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource
    from ceres.database import DatabaseType

__all__ = [
    "GroupPermission",
    "PermissionTargetType",
    "UserPermission",
]


class PermissionTargetType(StrEnum):
    """Discriminator for the kind of target a permission grant applies to."""

    COMPONENT = "component"
    """Grant applies to a specific component by address."""
    TAG = "tag"
    """Grant applies to all components carrying a given tag."""
    ALL = "all"
    """Grant applies to every component. The target string is empty."""


class UserPermissionRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `UserPermission` entity."""

    __tablename__: ClassVar[str] = "user_permissions"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper)
    target_type: Mapped[PermissionTargetType] = mapped_column(EnumMapper(PermissionTargetType))
    target: Mapped[str] = mapped_column(TextMapper())
    level: Mapped[ComponentAccessLevel] = mapped_column(EnumMapper(ComponentAccessLevel))

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(
                cls.user_id, cls.target_type, cls.target, name=f"pk_{cls.__tablename__}"
            ),
            ForeignKeyConstraint(
                [cls.user_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__user_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            EnumConstraint(
                cls.target_type,
                PermissionTargetType,
                name=f"ck_{cls.__tablename__}__target_type",
            ),
            CheckConstraint(
                cls.level.in_(["view", "operate", "manage"]),
                name=f"ck_{cls.__tablename__}__level",
            ),
        )


type UserPermissionField = Literal[
    "user_id",
    "target_type",
    "target",
    "level",
]
"""Field names selectable in `UserPermission` queries."""

type UserPermissionOrder = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "target_type",
    "target_type:asc",
    "target_type:desc",
    "target",
    "target:asc",
    "target:desc",
    "level",
    "level:asc",
    "level:desc",
]
"""Ordering keys accepted by `UserPermission` queries."""


class UserPermissionFilterArgs(
    BaseEntityFilterArgs[
        UserPermissionField,
        UserPermissionOrder,
    ],
    total=False,
):
    """Keyword-argument form of `UserPermissionFilter` for ergonomic call sites."""

    user_id: MaybeSequence[UUID] | None
    target_type: MaybeSequence[PermissionTargetType] | None
    target: MaybeSequence[str] | None
    level: MaybeSequence[ComponentAccessLevel] | None


class UserPermissionFilter(
    BaseEntityFilter[
        "UserPermission",
        UserPermissionField,
        UserPermissionOrder,
    ]
):
    """Filter for selecting `UserPermission` records."""

    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given user IDs."""
    target_type: MaybeSequence[PermissionTargetType] | None = None
    """Filter by `target_type` being equal to one or more given types."""
    target: MaybeSequence[str] | None = None
    """Filter by `target` being equal to one or more given target strings."""
    level: MaybeSequence[ComponentAccessLevel] | None = None
    """Filter by `level` being equal to one or more given access levels."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[UserPermissionRow]:
        return UserPermissionRow

    @override
    def _matches(self, obj: UserPermission) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.user_id, self.user_id):
            return False
        if not self._match_value(obj.target_type, self.target_type):
            return False
        if not self._match_value(obj.target, self.target):
            return False
        if not self._match_value(obj.level, self.level):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield self._sql_match_value(columns.user_id, self.user_id)
        if self.target_type is not None:
            yield self._sql_match_value(columns.target_type, self.target_type)
        if self.target is not None:
            yield self._sql_match_value(columns.target, self.target)
        if self.level is not None:
            yield self._sql_match_value(columns.level, self.level)

    @override
    def _get_default_order(self) -> MaybeSequence[UserPermissionOrder]:
        return "user_id", "target_type", "target"


class UserPermissionCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `UserPermission` record."""

    user_id: UUID
    """ID of the user receiving the permission grant."""
    target_type: PermissionTargetType
    """Whether this grant targets a component address or a tag."""
    target: str
    """Component address string or tag name, depending on `target_type`."""
    level: ComponentAccessLevel
    """Access level granted to the user for the target."""


class UserPermissionUpdate(TypedDict, total=False):
    """Partial update for an existing `UserPermission` record."""

    level: ComponentAccessLevel


class _BaseUserPermissionQuery(
    BaseEntityQuery[
        "UserPermission",
        UserPermissionFilter,
        UserPermissionUpdate,
        "UserPermissionQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: UserPermissionFilter | None = None,
        **kwargs: Unpack[UserPermissionFilterArgs],
    ) -> UserPermissionQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[UserPermissionQuery]:
        return UserPermissionQuery


class UserPermissionQuery(
    EntityQuery[
        "UserPermission",
        UserPermissionFilter,
        UserPermissionUpdate,
    ],
    _BaseUserPermissionQuery,
):
    """Query builder for `UserPermission` records."""

    __slots__ = ()


class UserPermissionManager(
    BaseEntityManager[
        "UserPermission",
        UserPermissionRow,
        UserPermissionCreate,
        UserPermissionUpdate,
        UserPermissionFilter,
        UserPermissionFilterArgs,
    ],
    _BaseUserPermissionQuery,
):
    """Database-bound manager for `UserPermission` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, UserPermission)

    async def get(
        self,
        user_id: UUID,
        target_type: PermissionTargetType,
        target: str,
        /,
    ) -> UserPermission | None:
        """Fetch a single permission grant by its composite key.

        Args:
            user_id: UUID of the user.
            target_type: Whether this grant targets a component or tag.
            target: Component address or tag name.

        Returns:
            The matching permission, or `None` if no grant exists.
        """
        return await self.where(user_id=user_id, target_type=target_type, target=target).first()


class UserPermission(
    UserPermissionCreate,
    ConcreteEntity[UserPermissionRow],
    slots=True,
):
    """Permission grant linking a `User` to a component access level on a target."""

    Manager = UserPermissionManager
    Create = UserPermissionCreate
    Update = UserPermissionUpdate
    Filter = UserPermissionFilter
    FilterArgs = UserPermissionFilterArgs
    Field = UserPermissionField
    Order = UserPermissionOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("user permission")


class GroupPermissionRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `GroupPermission` entity."""

    __tablename__: ClassVar[str] = "group_permissions"

    group_id: Mapped[UUID] = mapped_column(UUIDMapper)
    target_type: Mapped[PermissionTargetType] = mapped_column(EnumMapper(PermissionTargetType))
    target: Mapped[str] = mapped_column(TextMapper())
    level: Mapped[ComponentAccessLevel] = mapped_column(EnumMapper(ComponentAccessLevel))

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(
                cls.group_id, cls.target_type, cls.target, name=f"pk_{cls.__tablename__}"
            ),
            ForeignKeyConstraint(
                [cls.group_id],
                [GroupRow.id],
                name=f"fk_{cls.__tablename__}__group_id__groups__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            EnumConstraint(
                cls.target_type,
                PermissionTargetType,
                name=f"ck_{cls.__tablename__}__target_type",
            ),
            CheckConstraint(
                cls.level.in_(["view", "operate", "manage"]),
                name=f"ck_{cls.__tablename__}__level",
            ),
        )


type GroupPermissionField = Literal[
    "group_id",
    "target_type",
    "target",
    "level",
]
"""Field names selectable in `GroupPermission` queries."""

type GroupPermissionOrder = Literal[
    "group_id",
    "group_id:asc",
    "group_id:desc",
    "target_type",
    "target_type:asc",
    "target_type:desc",
    "target",
    "target:asc",
    "target:desc",
    "level",
    "level:asc",
    "level:desc",
]
"""Ordering keys accepted by `GroupPermission` queries."""


class GroupPermissionFilterArgs(
    BaseEntityFilterArgs[
        GroupPermissionField,
        GroupPermissionOrder,
    ],
    total=False,
):
    """Keyword-argument form of `GroupPermissionFilter` for ergonomic call sites."""

    group_id: MaybeSequence[UUID] | None
    target_type: MaybeSequence[PermissionTargetType] | None
    target: MaybeSequence[str] | None
    level: MaybeSequence[ComponentAccessLevel] | None


class GroupPermissionFilter(
    BaseEntityFilter[
        "GroupPermission",
        GroupPermissionField,
        GroupPermissionOrder,
    ]
):
    """Filter for selecting `GroupPermission` records."""

    group_id: MaybeSequence[UUID] | None = None
    """Filter by `group_id` being equal to one or more given group IDs."""
    target_type: MaybeSequence[PermissionTargetType] | None = None
    """Filter by `target_type` being equal to one or more given types."""
    target: MaybeSequence[str] | None = None
    """Filter by `target` being equal to one or more given target strings."""
    level: MaybeSequence[ComponentAccessLevel] | None = None
    """Filter by `level` being equal to one or more given access levels."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[GroupPermissionRow]:
        return GroupPermissionRow

    @override
    def _matches(self, obj: GroupPermission) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.group_id, self.group_id):
            return False
        if not self._match_value(obj.target_type, self.target_type):
            return False
        if not self._match_value(obj.target, self.target):
            return False
        if not self._match_value(obj.level, self.level):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.group_id is not None:
            yield self._sql_match_value(columns.group_id, self.group_id)
        if self.target_type is not None:
            yield self._sql_match_value(columns.target_type, self.target_type)
        if self.target is not None:
            yield self._sql_match_value(columns.target, self.target)
        if self.level is not None:
            yield self._sql_match_value(columns.level, self.level)

    @override
    def _get_default_order(self) -> MaybeSequence[GroupPermissionOrder]:
        return "group_id", "target_type", "target"


class GroupPermissionCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `GroupPermission` record."""

    group_id: UUID
    """ID of the group receiving the permission grant."""
    target_type: PermissionTargetType
    """Whether this grant targets a component address or a tag."""
    target: str
    """Component address string or tag name, depending on `target_type`."""
    level: ComponentAccessLevel
    """Access level granted to the group for the target."""


class GroupPermissionUpdate(TypedDict, total=False):
    """Partial update for an existing `GroupPermission` record."""

    level: ComponentAccessLevel


class _BaseGroupPermissionQuery(
    BaseEntityQuery[
        "GroupPermission",
        GroupPermissionFilter,
        GroupPermissionUpdate,
        "GroupPermissionQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: GroupPermissionFilter | None = None,
        **kwargs: Unpack[GroupPermissionFilterArgs],
    ) -> GroupPermissionQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[GroupPermissionQuery]:
        return GroupPermissionQuery


class GroupPermissionQuery(
    EntityQuery[
        "GroupPermission",
        GroupPermissionFilter,
        GroupPermissionUpdate,
    ],
    _BaseGroupPermissionQuery,
):
    """Query builder for `GroupPermission` records."""

    __slots__ = ()


class GroupPermissionManager(
    BaseEntityManager[
        "GroupPermission",
        GroupPermissionRow,
        GroupPermissionCreate,
        GroupPermissionUpdate,
        GroupPermissionFilter,
        GroupPermissionFilterArgs,
    ],
    _BaseGroupPermissionQuery,
):
    """Database-bound manager for `GroupPermission` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, GroupPermission)

    async def get(
        self,
        group_id: UUID,
        target_type: PermissionTargetType,
        target: str,
        /,
    ) -> GroupPermission | None:
        """Fetch a single permission grant by its composite key.

        Args:
            group_id: UUID of the group.
            target_type: Whether this grant targets a component or tag.
            target: Component address or tag name.

        Returns:
            The matching permission, or `None` if no grant exists.
        """
        return await self.where(group_id=group_id, target_type=target_type, target=target).first()


class GroupPermission(
    GroupPermissionCreate,
    ConcreteEntity[GroupPermissionRow],
    slots=True,
):
    """Permission grant linking a `Group` to a component access level on a target."""

    Manager = GroupPermissionManager
    Create = GroupPermissionCreate
    Update = GroupPermissionUpdate
    Filter = GroupPermissionFilter
    FilterArgs = GroupPermissionFilterArgs
    Field = GroupPermissionField
    Order = GroupPermissionOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("group permission")
