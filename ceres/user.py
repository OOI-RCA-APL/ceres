from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override
from uuid import UUID

from sqlalchemy import Boolean, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from ceres.__internal__.database.types import EnumConstraint, EnumMapper
from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.data import (
    EmailAddress,
    MaybeSequence,
    OrderedStrEnum,
    Password,
    PasswordHash,
    Username,
)

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource, NodeSource
    from ceres.database import DatabaseType

__all__ = [
    "User",
]


class UserRole(OrderedStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserRow(BaseUUIDEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "users"

    username: Mapped[Username] = mapped_column(Text)
    email: Mapped[EmailAddress] = mapped_column(Text)
    password: Mapped[PasswordHash] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        EnumMapper(UserRole),
        default=UserRole.OPERATOR,
        server_default=str(UserRole.OPERATOR),
    )
    disabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=expression.false(),
    )

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            UniqueConstraint(cls.username, name=f"uq_{cls.__tablename__}__username"),
            EnumConstraint(cls.role, UserRole, name=f"ck_{cls.__tablename__}__role"),
        )


type UserField = (
    BaseUUIDEntityField
    | Literal[
        "username",
        "email",
        "role",
        "disabled",
    ]
)
type UserOrder = (
    BaseUUIDEntityOrder
    | Literal[
        "username",
        "username:asc",
        "username:desc",
        "email",
        "email:asc",
        "email:desc",
        "role",
        "role:asc",
        "role:desc",
        "disabled",
        "disabled:asc",
        "disabled:desc",
    ]
)


class UserFilterArgs(BaseUUIDEntityFilterArgs[UserField, UserOrder], total=False):
    username: MaybeSequence[str] | None
    username_contains: MaybeSequence[str] | None
    username_prefix: MaybeSequence[str] | None
    username_suffix: MaybeSequence[str] | None
    email: MaybeSequence[EmailAddress] | None
    email_contains: MaybeSequence[str] | None
    email_prefix: MaybeSequence[str] | None
    email_suffix: MaybeSequence[str] | None
    role: MaybeSequence[UserRole] | None
    disabled: bool | None
    can_view_workspace: MaybeSequence[UUID] | None
    can_edit_workspace: MaybeSequence[UUID] | None
    can_own_workspace: MaybeSequence[UUID] | None
    has_workspace_membership: MaybeSequence[UUID] | None


class UserFilter(BaseUUIDEntityFilter["User", UserField, UserOrder]):
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
    role: MaybeSequence[UserRole] | None = None
    """Filter by `role` being one or more given roles."""
    disabled: bool | None = None
    """Filter by `disabled` being either `True` or `False`."""
    can_view_workspace: MaybeSequence[UUID] | None = None
    """Filter, matching only users who can view at least one of the given workspaces."""
    can_edit_workspace: MaybeSequence[UUID] | None = None
    """Filter, matching only users who can edit at least one of the given workspaces."""
    can_own_workspace: MaybeSequence[UUID] | None = None
    """Filter, matching only users who can own at least one of the given workspaces."""
    has_workspace_membership: MaybeSequence[UUID] | None = None
    """Filter, matching only users who have a membership in at least one of the given workspaces."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[UserRow]:
        return UserRow

    @override
    def _matches(self, obj: User) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.username, self.username):
            return False
        if not self._match_string_contains(obj.username, self.username_contains):
            return False
        if not self._match_string_prefix(obj.username, self.username_prefix):
            return False
        if not self._match_string_suffix(obj.username, self.username_suffix):
            return False

        if not self._match_string_equals(obj.email, self.email, insensitive=True):
            return False
        if not self._match_string_contains(obj.email, self.email_contains, insensitive=True):
            return False
        if not self._match_string_prefix(obj.email, self.email_prefix, insensitive=True):
            return False
        if not self._match_string_suffix(obj.email, self.email_suffix, insensitive=True):
            return False

        if not self._match_value(obj.role, self.role):
            return False
        if not self._match_value(obj.disabled, self.disabled):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.username is not None:
            yield self._sql_match_value(columns.username, self.username)
        if self.username_contains is not None:
            yield self._sql_match_string_contains(columns.username, self.username_contains)
        if self.username_prefix is not None:
            yield self._sql_match_string_prefix(columns.username, self.username_prefix)
        if self.username_suffix is not None:
            yield self._sql_match_string_suffix(columns.username, self.username_suffix)

        if self.email is not None:
            yield self._sql_match_value(columns.email, self.email)
        if self.email_contains is not None:
            yield self._sql_match_string_contains(
                columns.email, self.email_contains, insensitive=True
            )
        if self.email_prefix is not None:
            yield self._sql_match_string_prefix(columns.email, self.email_prefix, insensitive=True)
        if self.email_suffix is not None:
            yield self._sql_match_string_suffix(columns.email, self.email_suffix, insensitive=True)

        if self.role is not None:
            yield self._sql_match_value(columns.role, self.role)
        if self.disabled is not None:
            yield columns.disabled == self.disabled

        if (
            self.can_view_workspace is not None
            or self.can_edit_workspace is not None
            or self.can_own_workspace is not None
            or self.has_workspace_membership is not None
        ):
            from ceres.workspace import WorkspaceFilter, WorkspaceRow

            filter = WorkspaceFilter()
            if self.can_view_workspace is not None:
                filter = filter.with_overrides(WorkspaceFilter(viewable_by=self.id))
            if self.can_edit_workspace is not None:
                filter = filter.with_overrides(WorkspaceFilter(editable_by=self.id))
            if self.can_own_workspace is not None:
                filter = filter.with_overrides(WorkspaceFilter(manageable_by=self.id))
            if self.has_workspace_membership is not None:
                filter = filter.with_overrides(WorkspaceFilter(joined_by=self.id))

            yield filter.apply(select(WorkspaceRow.id), dialect).exists()

    @override
    def _get_default_order(self) -> MaybeSequence[UserOrder]:
        return "username"


class UserCreate(BaseUUIDEntityCreate, slots=True):
    username: Username
    email: EmailAddress
    password: Password | PasswordHash
    role: UserRole = UserRole.OPERATOR
    disabled: bool = False


class UserUpdate(TypedDict, total=False):
    username: Username
    email: EmailAddress
    password: Password | PasswordHash
    role: UserRole
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
    async def _assign_transform(self, assign: UserUpdate) -> UserUpdate:
        assign = await super()._assign_transform(assign)
        if "password" in assign:
            assign = {**assign}
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return assign


class UserQuery(
    EntityQuery[
        "User",
        UserFilter,
        UserUpdate,
    ],
    _BaseUserQuery,
):
    __slots__ = ()


class UserManager(
    BaseEntityManager[
        "User",
        UserRow,
        UserCreate,
        UserUpdate,
        UserFilter,
        UserFilterArgs,
    ],
    _BaseUserQuery,
):
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, User)

    async def get(self, id: UUID, /) -> User | None:
        return await self.where(id=id).first()

    @override
    async def _create_transform(self, data: UserCreate) -> User:
        fields = dict(data)
        fields["password"] = await self._maybe_hash_password(fields["password"])
        return User(**fields)


class BoundUserManager(UserManager, BaseNodeManager):
    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)


class User(BaseUUIDEntity, UserCreate, slots=True):
    Manager = UserManager
    BoundManager = BoundUserManager
    Row = UserRow
    Create = UserCreate
    Update = UserUpdate
    Filter = UserFilter
    FilterArgs = UserFilterArgs
    Field = UserField
    Order = UserOrder
    Role = UserRole

    __naming__: ClassVar[EntityNaming] = EntityNaming("user")

    password: PasswordHash
