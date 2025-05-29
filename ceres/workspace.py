from __future__ import annotations

from enum import StrEnum
from typing import (
    TYPE_CHECKING,
    ClassVar,
    Iterable,
    Literal,
    Self,
    TypeAlias,
    TypedDict,
    Unpack,
    override,
)
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    Text,
    case,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from ceres._internal import util
from ceres._internal.database.types import EnumConstraint, EnumMapper, UUIDMapper
from ceres._internal.entity import (
    BaseEntity,
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
    EntityQuery,
)
from ceres._internal.util import MatchMode
from ceres.data import (
    EmailStr,
    FromYAML,
    JSONSerializableDict,
    MaybeSequence,
    NonEmptyStr,
    OrderedStrEnum,
)
from ceres.user import UserRole, UserRow

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource
    from ceres.database import DatabaseType


class WorkspaceAccessRestriction(OrderedStrEnum):
    @classmethod
    @override
    def __order_mapping__(cls) -> dict[WorkspaceAccessRestriction, int]:
        return {
            cls.VIEWER: UserRole.VIEWER.order,
            cls.OPERATOR: UserRole.OPERATOR.order,
            cls.ADMIN: UserRole.ADMIN.order,
            cls.PRIVATE: UserRole.ADMIN.order + 1,
        }

    VIEWER = "viewer"
    OPERATOR = "operator"
    ADMIN = "admin"
    PRIVATE = "private"


class WorkspaceMembershipRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


class WorkspaceMembershipRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "workspace_memberships"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper)
    workspace_id: Mapped[UUID] = mapped_column(UUIDMapper)
    role: Mapped[WorkspaceMembershipRole] = mapped_column(EnumMapper(WorkspaceMembershipRole))
    data: Mapped[JSONSerializableDict | None] = mapped_column(JSON, default=None)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(cls.user_id, cls.workspace_id, name=f"pk_{cls.__tablename__}"),
            ForeignKeyConstraint(
                [cls.user_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__user_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            ForeignKeyConstraint(
                [cls.workspace_id],
                ["workspaces.id"],
                name=f"fk_{cls.__tablename__}__workspace_id__workspaces__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            EnumConstraint(cls.role, WorkspaceMembershipRole, name=f"ck_{cls.__tablename__}__role"),
        )


WorkspaceMembershipField: TypeAlias = Literal[
    "user_id",
    "workspace_id",
    "role",
    "data",
]
WorkspaceMembershipOrder: TypeAlias = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "workspace_id",
    "workspace_id:asc",
    "workspace_id:desc",
    "role",
    "role:asc",
    "role:desc",
]


class WorkspaceMembershipFilterArgs(
    BaseEntityFilterArgs[
        WorkspaceMembershipField,
        WorkspaceMembershipOrder,
    ],
    total=False,
):
    user_id: MaybeSequence[UUID] | None
    workspace_id: MaybeSequence[UUID] | None
    role: MaybeSequence[WorkspaceMembershipRole] | None


class WorkspaceMembershipFilter(
    BaseEntityFilter[
        "WorkspaceMembership",
        WorkspaceMembershipField,
        WorkspaceMembershipOrder,
    ]
):
    user_id: MaybeSequence[UUID] | None = None
    workspace_id: MaybeSequence[UUID] | None = None
    role: MaybeSequence[WorkspaceMembershipRole] | None = None

    @classmethod
    @override
    def _get_row_cls(cls) -> type[WorkspaceMembershipRow]:
        return WorkspaceMembershipRow

    @override
    def _matches(self, obj: WorkspaceMembership) -> bool:
        if not super()._matches(obj):
            return False

        if not util.match_value(obj.user_id, self.user_id):
            return False
        if not util.match_value(obj.workspace_id, self.workspace_id):
            return False
        if not util.match_value(obj.role, self.role):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield util.sql_match_value(columns.user_id, self.user_id)
        if self.workspace_id is not None:
            yield util.sql_match_value(columns.workspace_id, self.workspace_id)
        if self.role is not None:
            yield util.sql_match_value(columns.role, self.role)

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceMembershipOrder]:
        return "user_id", "workspace_id"


class WorkspaceMembershipCreate(BaseEntityCreate):
    user_id: UUID
    workspace_id: UUID
    role: WorkspaceMembershipRole
    data: FromYAML[JSONSerializableDict] | None = None


class WorkspaceMembershipUpdate(TypedDict, total=False):
    role: WorkspaceMembershipRole
    data: FromYAML[JSONSerializableDict] | None


class _BaseWorkspaceMembershipQuery(
    BaseEntityQuery[
        "WorkspaceMembership",
        WorkspaceMembershipFilter,
        WorkspaceMembershipUpdate,
        "WorkspaceMembershipQuery",
    ]
):
    @override
    def where(
        self,
        filter: WorkspaceMembershipFilter | None = None,
        **kwargs: Unpack[WorkspaceMembershipFilterArgs],
    ) -> WorkspaceMembershipQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[WorkspaceMembershipQuery]:
        return WorkspaceMembershipQuery


class WorkspaceMembershipQuery(
    EntityQuery[
        "WorkspaceMembership",
        WorkspaceMembershipFilter,
        WorkspaceMembershipUpdate,
    ],
    _BaseWorkspaceMembershipQuery,
):
    pass


class WorkspaceMembershipManager(
    BaseEntityManager[
        "WorkspaceMembership",
        WorkspaceMembershipRow,
        WorkspaceMembershipCreate,
        WorkspaceMembershipUpdate,
        WorkspaceMembershipFilter,
        WorkspaceMembershipFilterArgs,
    ],
    _BaseWorkspaceMembershipQuery,
):
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, WorkspaceMembership)

    async def get(self, user_id: UUID, workspace_id: UUID, /) -> WorkspaceMembership | None:
        return await self.where(user_id=user_id, workspace_id=workspace_id).first()


class WorkspaceMembership(BaseEntity, WorkspaceMembershipCreate):
    Manager: ClassVar[type[WorkspaceMembershipManager]] = WorkspaceMembershipManager
    Row: ClassVar[type[WorkspaceMembershipRow]] = WorkspaceMembershipRow
    Create: ClassVar[type[WorkspaceMembershipCreate]] = WorkspaceMembershipCreate
    Update: ClassVar[type[WorkspaceMembershipUpdate]] = WorkspaceMembershipUpdate
    Filter: ClassVar[type[WorkspaceMembershipFilter]] = WorkspaceMembershipFilter
    FilterArgs: ClassVar[type[WorkspaceMembershipFilterArgs]] = WorkspaceMembershipFilterArgs
    Field = WorkspaceMembershipField
    Order = WorkspaceMembershipOrder
    Role: ClassVar[type[WorkspaceMembershipRole]] = WorkspaceMembershipRole


def _access_levels_ge(
    access: WorkspaceAccessRestriction | UserRole,
) -> list[WorkspaceAccessRestriction]:
    return [current for current in WorkspaceAccessRestriction if current >= access]


def _membership_roles_ge(access: WorkspaceMembershipRole) -> list[WorkspaceMembershipRole]:
    return [current for current in WorkspaceMembershipRole if current >= access]


def _access_level_value(
    value: SQLColumnExpression[WorkspaceAccessRestriction] | SQLColumnExpression[UserRole],
) -> SQLColumnExpression[int | None]:
    return case(
        *[(value == current, current.order) for current in WorkspaceAccessRestriction],
    )


class WorkspaceRow(BaseUUIDEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "workspaces"

    name: Mapped[str] = mapped_column(Text)
    client: Mapped[str] = mapped_column(Text, default="console", server_default="console")
    default_viewership: Mapped[WorkspaceAccessRestriction] = mapped_column(
        EnumMapper(WorkspaceAccessRestriction),
        default=WorkspaceAccessRestriction.PRIVATE,
        server_default=str(WorkspaceAccessRestriction.PRIVATE),
    )
    default_editorship: Mapped[WorkspaceAccessRestriction] = mapped_column(
        EnumMapper(WorkspaceAccessRestriction),
        default=WorkspaceAccessRestriction.PRIVATE,
        server_default=str(WorkspaceAccessRestriction.PRIVATE),
    )
    default_ownership: Mapped[WorkspaceAccessRestriction] = mapped_column(
        EnumMapper(WorkspaceAccessRestriction),
        default=WorkspaceAccessRestriction.PRIVATE,
        server_default=str(WorkspaceAccessRestriction.PRIVATE),
    )
    data: Mapped[JSONSerializableDict] = mapped_column(
        JSON,
        default_factory=dict,
        server_default="{}",
    )

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(cls.id, name=f"pk_{cls.__tablename__}"),
            EnumConstraint(
                cls.default_viewership,
                WorkspaceAccessRestriction,
                name=f"ck_{cls.__tablename__}__default_viewership",
            ),
            EnumConstraint(
                cls.default_editorship,
                WorkspaceAccessRestriction,
                name=f"ck_{cls.__tablename__}__default_editorship",
            ),
            EnumConstraint(
                cls.default_ownership,
                WorkspaceAccessRestriction,
                name=f"ck_{cls.__tablename__}__default_ownership",
            ),
        )


WorkspaceField: TypeAlias = (
    BaseUUIDEntityField
    | Literal[
        "name",
        "client",
        "default_viewership",
        "default_editorship",
        "default_ownership",
        "data",
    ]
)
WorkspaceOrder: TypeAlias = (
    BaseUUIDEntityOrder
    | Literal[
        "name",
        "name:asc",
        "name:desc",
        "client",
        "client:asc",
        "client:desc",
        "default_viewership",
        "default_viewership:asc",
        "default_viewership:desc",
        "default_editorship",
        "default_editorship:asc",
        "default_editorship:desc",
        "default_ownership",
        "default_ownership:asc",
        "default_ownership:desc",
        "data",
        "data:asc",
        "data:desc",
    ]
)


class WorkspaceFilterArgs(BaseUUIDEntityFilterArgs[WorkspaceField, WorkspaceOrder], total=False):
    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None
    client: MaybeSequence[str] | None
    client_contains: MaybeSequence[str] | None
    client_prefix: MaybeSequence[str] | None
    client_suffix: MaybeSequence[str] | None
    default_viewership: MaybeSequence[WorkspaceAccessRestriction]
    default_editorship: MaybeSequence[WorkspaceAccessRestriction]
    default_ownership: MaybeSequence[WorkspaceAccessRestriction]
    viewable_by: UUID | None
    editable_by: UUID | None
    owned_by: UUID | None


class WorkspaceFilter(BaseUUIDEntityFilter["Workspace", WorkspaceField, WorkspaceOrder]):
    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given usernames."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""
    client: MaybeSequence[EmailStr] | None = None
    """Filter by `client` being equal to one or more given email addresses."""
    client_contains: MaybeSequence[str] | None = None
    """Filter by `client` containing one or more given substrings."""
    client_prefix: MaybeSequence[str] | None = None
    """Filter by `client` starting with one or more given prefixes."""
    client_suffix: MaybeSequence[str] | None = None
    """Filter by `client` ending with one or more given suffixes."""
    default_viewership: MaybeSequence[WorkspaceAccessRestriction] | None = None
    """Filter by `default_viewership` being equal to one or more given access levels."""
    default_editorship: MaybeSequence[WorkspaceAccessRestriction] | None = None
    """Filter by `default_editorship` being equal to one or more given access levels."""
    default_ownership: MaybeSequence[WorkspaceAccessRestriction] | None = None
    """Filter by `default_ownership` being equal to one or more given access levels."""
    viewable_by: UUID | None = None
    """Filter, matching only workspaces viewable by a given user ID."""
    editable_by: UUID | None = None
    """Filter, matching only workspaces editable by a given user ID."""
    owned_by: UUID | None = None
    """Filter, matching only workspaces owned by a given user ID."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[WorkspaceRow]:
        return WorkspaceRow

    @override
    def _matches(self, obj: Workspace) -> bool:
        if not super()._matches(obj):
            return False

        if not util.match_value(obj.name, self.name):
            return False
        if not util.match_string(obj.name, self.name_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.name, self.name_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.name, self.name_suffix, MatchMode.SUFFIX):
            return False

        if not util.match_string(obj.client, self.client, MatchMode.EQUALS):
            return False
        if not util.match_string(obj.client, self.client_contains, MatchMode.CONTAINS):
            return False
        if not util.match_string(obj.client, self.client_prefix, MatchMode.PREFIX):
            return False
        if not util.match_string(obj.client, self.client_suffix, MatchMode.SUFFIX):
            return False

        if not util.match_value(obj.default_viewership, self.default_viewership):
            return False
        if not util.match_value(obj.default_editorship, self.default_editorship):
            return False
        if not util.match_value(obj.default_ownership, self.default_ownership):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.name is not None:
            yield util.sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield util.sql_match_string(columns.name, self.name_contains, MatchMode.CONTAINS)
        if self.name_prefix is not None:
            yield util.sql_match_string(columns.name, self.name_prefix, MatchMode.PREFIX)
        if self.name_suffix is not None:
            yield util.sql_match_string(columns.name, self.name_suffix, MatchMode.SUFFIX)

        if self.client is not None:
            yield util.sql_match_value(columns.client, self.client)
        if self.client_contains is not None:
            yield util.sql_match_string(columns.client, self.client_contains, MatchMode.CONTAINS)
        if self.client_prefix is not None:
            yield util.sql_match_string(columns.client, self.client_prefix, MatchMode.PREFIX)
        if self.client_suffix is not None:
            yield util.sql_match_string(columns.client, self.client_suffix, MatchMode.SUFFIX)

        if self.default_viewership is not None:
            yield util.sql_match_value(columns.default_viewership, self.default_viewership)
        if self.default_editorship is not None:
            yield util.sql_match_value(columns.default_editorship, self.default_editorship)
        if self.default_ownership is not None:
            yield util.sql_match_value(columns.default_ownership, self.default_ownership)

        for user_id, default_access_level, min_membership_role in (
            (self.viewable_by, columns.default_viewership, WorkspaceMembershipRole.VIEWER),
            (self.editable_by, columns.default_editorship, WorkspaceMembershipRole.EDITOR),
            (self.owned_by, columns.default_ownership, WorkspaceMembershipRole.OWNER),
        ):
            if user_id is None:
                continue

            yield columns.id.in_(
                select(columns.id)
                .join(WorkspaceMembershipRow)
                .join(UserRow)
                .where(
                    _access_level_value(UserRow.role) >= _access_level_value(default_access_level)
                )
            ) | (
                columns.id.in_(
                    select(WorkspaceMembershipRow.workspace_id).where(
                        WorkspaceMembershipRow.user_id == user_id,
                        WorkspaceMembershipRow.role.in_(_membership_roles_ge(min_membership_role)),
                    )
                )
            )

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceOrder]:
        return "name"


class WorkspaceCreate(BaseUUIDEntityCreate):
    name: NonEmptyStr
    client: str = "console"
    default_viewership: WorkspaceAccessRestriction = WorkspaceAccessRestriction.PRIVATE
    default_editorship: WorkspaceAccessRestriction = WorkspaceAccessRestriction.PRIVATE
    default_ownership: WorkspaceAccessRestriction = WorkspaceAccessRestriction.PRIVATE
    data: FromYAML[JSONSerializableDict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        default_editorship_restriction = (
            self.default_editorship.order if self.default_editorship is not None else -1
        )
        default_viewership_value = (
            self.default_viewership.order if self.default_viewership is not None else -1
        )
        default_ownership_restriction = (
            self.default_ownership.order if self.default_ownership is not None else -1
        )
        if default_editorship_restriction < default_viewership_value:
            raise ValueError(
                "`default_editorship` must be as or more restrictive than `default_viewership`"
            )
        if default_ownership_restriction < default_editorship_restriction:
            raise ValueError(
                "`default_ownership` must be as or more restrictive than `default_editorship`"
            )

        return self


class WorkspaceUpdate(TypedDict, total=False):
    name: NonEmptyStr
    client: str
    default_viewership: WorkspaceAccessRestriction
    default_editorship: WorkspaceAccessRestriction
    default_ownership: WorkspaceAccessRestriction
    data: JSONSerializableDict


class _BaseWorkspaceQuery(
    BaseEntityQuery[
        "Workspace",
        WorkspaceFilter,
        WorkspaceUpdate,
        "WorkspaceQuery",
    ]
):
    @override
    def where(
        self,
        filter: WorkspaceFilter | None = None,
        **kwargs: Unpack[WorkspaceFilterArgs],
    ) -> WorkspaceQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[WorkspaceQuery]:
        return WorkspaceQuery


class WorkspaceQuery(
    EntityQuery[
        "Workspace",
        WorkspaceFilter,
        WorkspaceUpdate,
    ],
    _BaseWorkspaceQuery,
):
    pass


class WorkspaceManager(
    BaseEntityManager[
        "Workspace",
        WorkspaceRow,
        WorkspaceCreate,
        WorkspaceUpdate,
        WorkspaceFilter,
        WorkspaceFilterArgs,
    ],
    _BaseWorkspaceQuery,
):
    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Workspace)

    async def get(self, id: UUID, /) -> Workspace | None:
        return await self.where(id=id).first()


class Workspace(BaseUUIDEntity, WorkspaceCreate):
    Manager: ClassVar[type[WorkspaceManager]] = WorkspaceManager
    Row: ClassVar[type[WorkspaceRow]] = WorkspaceRow
    Create: ClassVar[type[WorkspaceCreate]] = WorkspaceCreate
    Update: ClassVar[type[WorkspaceUpdate]] = WorkspaceUpdate
    Filter: ClassVar[type[WorkspaceFilter]] = WorkspaceFilter
    FilterArgs: ClassVar[type[WorkspaceFilterArgs]] = WorkspaceFilterArgs
    Field = WorkspaceField
    Order = WorkspaceOrder
    Role: ClassVar[type[UserRole]] = UserRole
