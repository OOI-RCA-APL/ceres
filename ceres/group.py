from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    BaseUUIDEntity,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.models.groups import (
    GroupCreate,
    GroupField,
    GroupFilter,
    GroupFilterArgs,
    GroupMembershipCreate,
    GroupMembershipField,
    GroupMembershipFilter,
    GroupMembershipFilterArgs,
    GroupMembershipOrder,
    GroupMembershipUpdate,
    GroupOrder,
    GroupUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource

__all__ = [
    "Group",
    "GroupMembership",
]


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
    ConcreteEntity,
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
    ConcreteEntity,
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
