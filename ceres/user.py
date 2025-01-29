from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    AsyncIterable,
    ClassVar,
    Iterable,
    Literal,
    TypeAlias,
    TypedDict,
    Unpack,
    override,
)

from sqlalchemy import Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import SchemaItem, UniqueConstraint
from sqlalchemy.sql import SQLColumnExpression, expression

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.entity import (
    BaseEntityManager,
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
)
from ceres.data import (
    EmailStr,
    MaybeSequence,
    PasswordHash,
    PasswordStr,
    PriorityStrEnum,
    UsernameStr,
)
from ceres.database import DatabaseType


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserRow(BaseUUIDEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "users"

    username: Mapped[UsernameStr] = mapped_column(Text)
    email: Mapped[EmailStr] = mapped_column(Text)
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
            UniqueConstraint("username", name=f"uq_{cls.__tablename__}__username"),
            EnumConstraint("role", UserRole, name=f"ck_{cls.__tablename__}__role"),
        )


UserField: TypeAlias = BaseUUIDEntityField | Literal["username", "email", "role", "disabled"]
UserOrder: TypeAlias = (
    BaseUUIDEntityOrder
    | Literal[
        "username",
        "-username",
        "email",
        "-email",
        "role",
        "-role",
        "disabled",
        "-disabled",
    ]
)


class UserFilterArgs(BaseUUIDEntityFilterArgs[UserField, UserOrder], total=False):
    username: MaybeSequence[str] | None
    email: MaybeSequence[str] | None
    role: MaybeSequence[UserRole] | None
    disabled: bool | None


class UserFilter(BaseUUIDEntityFilter["User", UserField, UserOrder]):
    username: MaybeSequence[str] | None = None
    """Filter by `username` being equal to one or more given usernames."""
    email: MaybeSequence[str] | None = None
    """Filter by `email` being equal to one or more given email addresses."""
    role: MaybeSequence[UserRole] | None = None
    """Filter by `role` being one or more given roles."""
    disabled: bool | None = None
    """Filter by `disabled` being either `True` or `False`."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[UserRow]:
        return UserRow

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.username is not None:
            yield columns.username.in_(util.as_sequence(self.username))
        if self.email is not None:
            yield columns.email.in_(util.as_sequence(self.email))
        if self.role is not None:
            yield columns.role.in_(util.as_sequence(self.role))
        if self.disabled is not None:
            yield columns.disabled == self.disabled

    @override
    def _get_default_order(self) -> UserOrder:
        return "username"


class UserCreate(BaseUUIDEntityCreate):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr | PasswordHash
    role: UserRole = UserRole.OPERATOR
    disabled: bool = False


class UserUpdate(TypedDict, total=False):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr | PasswordHash
    role: UserRole
    disabled: bool


class User(BaseUUIDEntity, UserCreate):
    Row: ClassVar[type[UserRow]] = UserRow
    Create: ClassVar[type[UserCreate]] = UserCreate
    Update: ClassVar[type[UserUpdate]] = UserUpdate
    Filter: ClassVar[type[UserFilter]] = UserFilter
    FilterArgs: ClassVar[type[UserFilterArgs]] = UserFilterArgs
    Field = UserField
    Order = UserOrder

    password: PasswordHash


if TYPE_CHECKING:
    from ceres.data import PasswordHash
    from ceres.database import Database
    from ceres.node import Node


class UserManager(
    BaseEntityManager[
        User,
        User.Row,
        User.Create,
        User.Update,
        User.Filter,
        User.FilterArgs,
    ]
):
    def __init__(self, source: Database | Node, /) -> None:
        super().__init__(source, User)

    @override
    async def update_all(self, filter: UserFilter, assign: UserUpdate) -> int:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update_all(filter, assign)

    @override
    async def update(self, filter: UserFilter, assign: UserUpdate) -> User | None:
        if "password" in assign:
            assign["password"] = await self._maybe_hash_password(assign["password"])

        return await super().update(filter, assign)

    @override
    async def _from_create(self, data: UserCreate) -> User:
        fields = {**data.__dict__}
        fields["password"] = await self._maybe_hash_password(fields["password"])
        return User(**fields)

    async def _maybe_hash_password(self, password: str) -> PasswordHash:
        from ceres._internal.auth import verify_password_hash

        if verify_password_hash(password):
            return password

        return await self._database.hash_password(password)

    if TYPE_CHECKING:
        # See: https://github.com/python/typing/issues/1399
        _E = User
        _F = User.Filter
        _FA = User.FilterArgs

        @override
        async def get_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> list[_E]: ...

        @override
        async def get(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        def select(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> AsyncIterable[_E]: ...

        @override
        async def delete_all(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...

        @override
        async def delete(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> _E | None: ...

        @override
        async def count(  # pyright: ignore[reportIncompatibleMethodOverride]
            self, filter: _F | None = None, **kwargs: Unpack[_FA]
        ) -> int: ...
