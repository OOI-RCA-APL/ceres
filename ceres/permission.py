from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.models.permissions import (
    GroupPermissionCreate,
    GroupPermissionField,
    GroupPermissionFilter,
    GroupPermissionFilterArgs,
    GroupPermissionOrder,
    GroupPermissionUpdate,
    PermissionTargetType,
    UserPermissionCreate,
    UserPermissionField,
    UserPermissionFilter,
    UserPermissionFilterArgs,
    UserPermissionOrder,
    UserPermissionUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource

__all__ = [
    "GroupPermission",
    "PermissionTargetType",
    "UserPermission",
]


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
    ConcreteEntity,
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
    ConcreteEntity,
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
