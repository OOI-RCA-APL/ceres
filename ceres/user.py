from __future__ import annotations

from typing import Annotated, Any, ClassVar, Iterable, Sequence, TypedDict, override
from uuid import UUID, uuid4

from pydantic import Field

from ceres._internal.cli.plumbing import CLIOption
from ceres._internal.database.types import EnumConstraint, EnumMapper
from ceres._internal.lazy import lazy_imports
from ceres.data import (
    EmailStr,
    PasswordHash,
    PasswordStr,
    PriorityStrEnum,
    StrEnum,
    UsernameStr,
)
from ceres.database.enums import DatabaseType
from ceres.entity import (
    BaseEntity,
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityRow,
)

with lazy_imports(__name__):
    from sqlalchemy.orm import Mapped, QueryableAttribute, mapped_column
    from sqlalchemy.schema import SchemaItem, UniqueConstraint
    from sqlalchemy.sql import ColumnExpressionArgument, expression
    from sqlalchemy.sql.sqltypes import Boolean, Text

    from ceres._internal import util


class UserRole(PriorityStrEnum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"


class UserRow(BaseEntityRow, kw_only=True):
    __tablename__ = "users"

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


class UserOrder(StrEnum):
    USERNAME = "username"
    EMAIL = "email"


class UserFilterArgs(BaseEntityFilterArgs, total=False):
    username: str | Sequence[str] | None
    email: str | Sequence[str] | None
    role: UserRole | Sequence[UserRole] | None
    disabled: bool | None
    order: UserOrder | None
    limit: int | None
    offset: int | None


class UserFilter(BaseEntityFilter["User"]):
    username: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by username(s).",
    )
    email: Annotated[str | Sequence[str] | None, CLIOption(list[str] | None)] = Field(
        default=None,
        description="Filter by user email(s).",
    )
    role: Annotated[UserRole | Sequence[UserRole] | None, CLIOption(list[UserRole] | None)] = Field(
        default=None,
        description="Filter by user role(s).",
    )
    disabled: Annotated[bool | None, CLIOption(bool | None)] = Field(
        default=None,
        description="Filter by disabled/enabled status.",
    )
    order: Annotated[UserOrder | None, CLIOption(UserOrder | None)] = Field(
        default=None,
        description="Specify order of resulting users.",
    )

    @override
    def _get_row_cls(self) -> type[UserRow]:
        return UserRow

    @override
    def _get_search_content(self, obj: User) -> dict[str, str]:
        return {
            "username": obj.username,
            "email": obj.email,
            "role": obj.role,
        }

    @override
    def _get_database_search_content(
        self,
        dialect: DatabaseType,
    ) -> dict[str, QueryableAttribute[str | bytes]]:
        columns = self._get_row_cls()

        return {
            "username": columns.username,
            "email": columns.email,
            "role": columns.role,
        }

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[ColumnExpressionArgument[bool]]:
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
    def _get_order_by(self) -> ColumnExpressionArgument[Any]:
        columns = self._get_row_cls()
        match self.order:
            case None | UserOrder.USERNAME:
                return columns.username
            case UserOrder.EMAIL:
                return columns.email


class UserCreate(BaseEntityCreate):
    id: Annotated[UUID, CLIOption(UUID)] = Field(default_factory=uuid4)
    username: Annotated[UsernameStr, CLIOption(str)]
    email: Annotated[EmailStr, CLIOption(str)]
    password: Annotated[PasswordStr | PasswordHash, CLIOption(str, prompt=True, hide_input=True)]
    role: Annotated[UserRole, CLIOption(UserRole)] = UserRole.OPERATOR
    disabled: Annotated[bool, CLIOption(bool)] = False


class UserUpdate(TypedDict, total=False):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr | PasswordHash
    role: UserRole
    disabled: bool


class User(BaseEntity, UserCreate):
    Order: ClassVar[type[UserOrder]] = UserOrder

    Row: ClassVar[type[UserRow]] = UserRow
    Create: ClassVar[type[UserCreate]] = UserCreate
    Update: ClassVar[type[UserUpdate]] = UserUpdate
    Filter: ClassVar[type[UserFilter]] = UserFilter
    FilterArgs: ClassVar[type[UserFilterArgs]] = UserFilterArgs

    password: Annotated[PasswordHash, CLIOption(str, prompt=True, hide_input=True)]
