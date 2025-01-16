from __future__ import annotations

from typing import (
    ClassVar,
    Iterable,
    Literal,
    Sequence,
    TypeAlias,
    TypedDict,
    override,
)
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.sqltypes import Boolean, Text

from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.entity import (
    BaseUUIDEntity,
    BaseUUIDEntityCreate,
    BaseUUIDEntityField,
    BaseUUIDEntityFilter,
    BaseUUIDEntityFilterArgs,
    BaseUUIDEntityOrder,
    BaseUUIDEntityRow,
)
from ceres._internal.lazy import lazy_imports
from ceres.data import (
    EmailStr,
    PasswordHash,
    PasswordStr,
    PriorityStrEnum,
    UsernameStr,
)
from ceres.database.enums import DatabaseType

with lazy_imports(__name__):
    from sqlalchemy.schema import SchemaItem, UniqueConstraint
    from sqlalchemy.sql import SQLColumnExpression, expression

    from ceres._internal import util


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
    username: str | Sequence[str] | None
    email: str | Sequence[str] | None
    role: UserRole | Sequence[UserRole] | None
    disabled: bool | None


class UserFilter(BaseUUIDEntityFilter["User", UserField, UserOrder]):
    username: str | Sequence[str] | None = None
    """Filter by `username` being equal to one or more given usernames."""
    email: str | Sequence[str] | None = None
    """Filter by `email` being equal to one or more given email addresses."""
    role: UserRole | Sequence[UserRole] | None = None
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
    id: UUID = Field(default_factory=uuid4)
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
