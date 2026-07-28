from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override
from uuid import UUID

from sqlalchemy import ForeignKeyConstraint, PrimaryKeyConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import TextMapper, UUIDMapper
from ceres.__internal__.entity import (
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityManager,
    BaseEntityQuery,
    BaseEntityRow,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.data import MaybeSequence, Name
from ceres.user import UserRow

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource
    from ceres.database import DatabaseType

__all__ = [
    "Group",
    "GroupMembership",
]


class GroupRow(BaseUUIDEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `Group` entity."""

    __tablename__: ClassVar[str] = "groups"

    name: Mapped[str] = mapped_column(TextMapper())
    description: Mapped[str] = mapped_column(TextMapper(), default="", server_default="")

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            UniqueConstraint(cls.name, name=f"uq_{cls.__tablename__}__name"),
        )


type GroupField = (
    BaseUUIDEntityField
    | Literal[
        "name",
        "description",
    ]
)
"""Field names selectable in `Group` queries."""

type GroupOrder = (
    BaseUUIDEntityOrder
    | Literal[
        "name",
        "name:asc",
        "name:desc",
        "description",
        "description:asc",
        "description:desc",
    ]
)
"""Ordering keys accepted by `Group` queries."""


class GroupFilterArgs(BaseUUIDEntityFilterArgs[GroupField, GroupOrder], total=False):
    """Keyword-argument form of `GroupFilter` for ergonomic call sites."""

    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None


class GroupFilter(BaseUUIDEntityFilter["Group", GroupField, GroupOrder]):
    """Filter for selecting `Group` records by name."""

    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given names."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[GroupRow]:
        return GroupRow

    @override
    def _matches(self, obj: Group) -> bool:
        if not super()._matches(obj):
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

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.name is not None:
            yield self._sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield self._sql_match_string_contains(columns.name, self.name_contains)
        if self.name_prefix is not None:
            yield self._sql_match_string_prefix(columns.name, self.name_prefix)
        if self.name_suffix is not None:
            yield self._sql_match_string_suffix(columns.name, self.name_suffix)

    @override
    def _get_default_order(self) -> MaybeSequence[GroupOrder]:
        return "name"


class GroupCreate(BaseUUIDEntityCreate, slots=True):
    """Payload for creating a new `Group` record."""

    name: Name
    """Unique name identifying the group in the system."""
    description: str = ""
    """Human-readable description of the group's purpose."""


class GroupUpdate(TypedDict, total=False):
    """Partial update for an existing `Group` record."""

    name: Name
    description: str


class _BaseGroupQuery(
    BaseEntityQuery[
        "Group",
        GroupFilter,
        GroupUpdate,
        "GroupQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: GroupFilter | None = None,
        **kwargs: Unpack[GroupFilterArgs],
    ) -> GroupQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[GroupQuery]:
        return GroupQuery


class GroupQuery(
    EntityQuery[
        "Group",
        GroupFilter,
        GroupUpdate,
    ],
    _BaseGroupQuery,
):
    """Query builder for `Group` records."""

    __slots__ = ()


class GroupManager(
    BaseEntityManager[
        "Group",
        GroupRow,
        GroupCreate,
        GroupUpdate,
        GroupFilter,
        GroupFilterArgs,
    ],
    _BaseGroupQuery,
):
    """Database-bound manager for `Group` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Group)

    async def get(self, id: UUID, /) -> Group | None:
        """Fetch a single group by its identifier.

        Args:
            id: UUID of the group to fetch.

        Returns:
            The matching group, or `None` if no group with that id exists.
        """
        return await self.where(id=id).first()


class Group(
    BaseUUIDEntity,
    GroupCreate,
    ConcreteEntity[GroupRow],
    slots=True,
):
    """Named collection of users used to grant shared component permissions.

    Each group has a unique `name` and an optional `description`. Users join a group through a
    `GroupMembership`, which is later used to grant component access levels to every member at
    once.
    """

    Manager = GroupManager
    Create = GroupCreate
    Update = GroupUpdate
    Filter = GroupFilter
    FilterArgs = GroupFilterArgs
    Field = GroupField
    Order = GroupOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("group")


class GroupMembershipRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `GroupMembership` entity."""

    __tablename__: ClassVar[str] = "group_memberships"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper)
    group_id: Mapped[UUID] = mapped_column(UUIDMapper)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(cls.user_id, cls.group_id, name=f"pk_{cls.__tablename__}"),
            ForeignKeyConstraint(
                [cls.user_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__user_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            ForeignKeyConstraint(
                [cls.group_id],
                [GroupRow.id],
                name=f"fk_{cls.__tablename__}__group_id__groups__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )


type GroupMembershipField = Literal[
    "user_id",
    "group_id",
]
"""Field names selectable in `GroupMembership` queries."""

type GroupMembershipOrder = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "group_id",
    "group_id:asc",
    "group_id:desc",
]
"""Ordering keys accepted by `GroupMembership` queries."""


class GroupMembershipFilterArgs(
    BaseEntityFilterArgs[
        GroupMembershipField,
        GroupMembershipOrder,
    ],
    total=False,
):
    """Keyword-argument form of `GroupMembershipFilter` for ergonomic call sites."""

    user_id: MaybeSequence[UUID] | None
    group_id: MaybeSequence[UUID] | None


class GroupMembershipFilter(
    BaseEntityFilter[
        "GroupMembership",
        GroupMembershipField,
        GroupMembershipOrder,
    ]
):
    """Filter for selecting `GroupMembership` records by user or group."""

    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given user IDs."""
    group_id: MaybeSequence[UUID] | None = None
    """Filter by `group_id` being equal to one or more given group IDs."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[GroupMembershipRow]:
        return GroupMembershipRow

    @override
    def _matches(self, obj: GroupMembership) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.user_id, self.user_id):
            return False
        if not self._match_value(obj.group_id, self.group_id):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield self._sql_match_value(columns.user_id, self.user_id)
        if self.group_id is not None:
            yield self._sql_match_value(columns.group_id, self.group_id)

    @override
    def _get_default_order(self) -> MaybeSequence[GroupMembershipOrder]:
        return "user_id", "group_id"


class GroupMembershipCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `GroupMembership` record."""

    user_id: UUID
    """ID of the user being added to the group."""
    group_id: UUID
    """ID of the group the user is joining."""


class GroupMembershipUpdate(TypedDict, total=False):
    """Partial update for an existing `GroupMembership` record.

    Memberships are only created or deleted, so this update payload has no mutable fields.
    """


class _BaseGroupMembershipQuery(
    BaseEntityQuery[
        "GroupMembership",
        GroupMembershipFilter,
        GroupMembershipUpdate,
        "GroupMembershipQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: GroupMembershipFilter | None = None,
        **kwargs: Unpack[GroupMembershipFilterArgs],
    ) -> GroupMembershipQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[GroupMembershipQuery]:
        return GroupMembershipQuery


class GroupMembershipQuery(
    EntityQuery[
        "GroupMembership",
        GroupMembershipFilter,
        GroupMembershipUpdate,
    ],
    _BaseGroupMembershipQuery,
):
    """Query builder for `GroupMembership` records."""

    __slots__ = ()


class GroupMembershipManager(
    BaseEntityManager[
        "GroupMembership",
        GroupMembershipRow,
        GroupMembershipCreate,
        GroupMembershipUpdate,
        GroupMembershipFilter,
        GroupMembershipFilterArgs,
    ],
    _BaseGroupMembershipQuery,
):
    """Database-bound manager for `GroupMembership` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, GroupMembership)

    async def get(self, user_id: UUID, group_id: UUID, /) -> GroupMembership | None:
        """Fetch the membership linking a user and group, if one exists.

        Args:
            user_id: UUID of the user.
            group_id: UUID of the group.

        Returns:
            The matching membership, or `None` if the user is not a member of the group.
        """
        return await self.where(user_id=user_id, group_id=group_id).first()


class GroupMembership(
    GroupMembershipCreate,
    ConcreteEntity[GroupMembershipRow],
    slots=True,
):
    """Association record linking a `User` to a `Group`."""

    Manager = GroupMembershipManager
    Create = GroupMembershipCreate
    Update = GroupMembershipUpdate
    Filter = GroupMembershipFilter
    FilterArgs = GroupMembershipFilterArgs
    Field = GroupMembershipField
    Order = GroupMembershipOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("group membership")
