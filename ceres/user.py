from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    BaseUUIDEntity,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.models.users import (
    UserCreate,
    UserField,
    UserFilter,
    UserFilterArgs,
    UserOrder,
    UserUpdate,
)
from ceres.data import PasswordHash

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource, NodeSource

__all__ = [
    "User",
]


class _BaseUserQuery(
    BaseEntityQuery[
        "User",
        UserFilter,
        UserUpdate,
        "UserQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: UserFilter | None = None,
        **kwargs: Unpack[UserFilterArgs],
    ) -> UserQuery:
        return super().where(filter, **kwargs)

    async def _maybe_hash_password(self, password: str) -> PasswordHash:
        from ceres.__internal__.auth import verify_password_hash

        if verify_password_hash(password):
            return password

        return await self._get_database().hash_password(password)

    @override
    def _get_query_class(self) -> type[UserQuery]:
        return UserQuery

    @override
    async def _set_transform(self, set: UserUpdate) -> UserUpdate:
        set = await super()._set_transform(set)
        if "password" in set:
            set = {**set}
            set["password"] = await self._maybe_hash_password(set["password"])

        return set


class UserQuery(
    EntityQuery[
        "User",
        UserFilter,
        UserUpdate,
    ],
    _BaseUserQuery,
):
    """Query builder for `User` records."""

    __slots__ = ()


class UserManager(
    BaseEntityManager[
        "User",
        UserCreate,
        UserUpdate,
        UserFilter,
        UserFilterArgs,
    ],
    _BaseUserQuery,
):
    """Database-bound manager for `User` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, User)

    async def get(self, id: UUID, /) -> User | None:
        """Fetch a single user by their identifier.

        Args:
            id: UUID of the user to fetch.

        Returns:
            The matching user, or `None` if no user with that id exists.
        """
        return await self.where(id=id).first()

    @override
    async def _create_transform(self, data: UserCreate) -> User:
        fields = dict(data)
        fields["password"] = await self._maybe_hash_password(fields["password"])
        return User(**fields)


class BoundUserManager(UserManager, BaseNodeManager):
    """Component-bound user manager exposed to nodes."""

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)


class User(
    BaseUUIDEntity,
    UserCreate,
    ConcreteEntity,
    slots=True,
):
    """Authenticated account with an `admin` flag that governs access to workspaces and resources.

    Each user has a unique `username`, an `email`, a hashed `password`, and an `admin` flag that
    grants full access when set. Users may additionally be granted or restricted from specific
    workspaces and components via memberships and permission grants.
    """

    Manager = UserManager
    BoundManager = BoundUserManager
    Create = UserCreate
    Update = UserUpdate
    Filter = UserFilter
    FilterArgs = UserFilterArgs
    Field = UserField
    Order = UserOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("user")

    password: PasswordHash
