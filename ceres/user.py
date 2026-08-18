from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.data import (
    EmailAddress,
    MaybeSequence,
    Password,
    PasswordHash,
    Username,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource, NodeSource

__all__ = [
    "User",
]


type UserField = (
    BaseUUIDEntityField
    | Literal[
        "username",
        "email",
        "admin",
        "disabled",
    ]
)
"""Field names selectable in `User` queries."""

type UserOrder = (
    BaseUUIDEntityOrder
    | Literal[
        "username",
        "username:asc",
        "username:desc",
        "email",
        "email:asc",
        "email:desc",
        "admin",
        "admin:asc",
        "admin:desc",
        "disabled",
        "disabled:asc",
        "disabled:desc",
    ]
)
"""Ordering keys accepted by `User` queries."""


class UserFilterArgs(BaseUUIDEntityFilterArgs[UserField, UserOrder], total=False):
    """Keyword-argument form of `UserFilter` for ergonomic call sites."""

    username: MaybeSequence[str] | None
    username_contains: MaybeSequence[str] | None
    username_prefix: MaybeSequence[str] | None
    username_suffix: MaybeSequence[str] | None
    email: MaybeSequence[EmailAddress] | None
    email_contains: MaybeSequence[str] | None
    email_prefix: MaybeSequence[str] | None
    email_suffix: MaybeSequence[str] | None
    admin: bool | None
    disabled: bool | None


class UserFilter(BaseUUIDEntityFilter["User", UserField, UserOrder]):
    """Filter for selecting `User` records by identity or admin status."""

    __table__: ClassVar[str] = "users"

    username: MaybeSequence[str] | None = None
    """Filter by `username` being equal to one or more given usernames."""
    username_contains: MaybeSequence[str] | None = None
    """Filter by `username` containing one or more given substrings."""
    username_prefix: MaybeSequence[str] | None = None
    """Filter by `username` starting with one or more given prefixes."""
    username_suffix: MaybeSequence[str] | None = None
    """Filter by `username` ending with one or more given suffixes."""
    email: MaybeSequence[EmailAddress] | None = None
    """Filter by `email` being equal to one or more given email addresses."""
    email_contains: MaybeSequence[str] | None = None
    """Filter by `email` containing one or more given substrings."""
    email_prefix: MaybeSequence[str] | None = None
    """Filter by `email` starting with one or more given prefixes."""
    email_suffix: MaybeSequence[str] | None = None
    """Filter by `email` ending with one or more given suffixes."""
    admin: bool | None = None
    """Filter by `admin` being either `True` or `False`."""
    disabled: bool | None = None
    """Filter by `disabled` being either `True` or `False`."""


class UserCreate(BaseUUIDEntityCreate, slots=True):
    """Payload for creating a new `User` record."""

    username: Username
    """Unique name identifying the user in the system."""
    email: EmailAddress
    """Email address associated with the user."""
    password: Password | PasswordHash
    """Plaintext password or pre-computed hash, plaintext values are hashed on create."""
    admin: bool = False
    """Whether the user has administrative access to all components and workspaces."""
    disabled: bool = False
    """Whether the user account is disabled and unable to authenticate."""


class UserUpdate(TypedDict, total=False):
    """Partial update for an existing `User` record."""

    username: Username
    email: EmailAddress
    password: Password | PasswordHash
    admin: bool
    disabled: bool


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
