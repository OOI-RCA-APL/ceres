from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    ClassVar,
    Literal,
    Self,
    TypedDict,
    Unpack,
    override,
)
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    Text,
    case,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.elements import literal_column

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
    BaseEntityUpdate,
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
from ceres._internal.util import MatchMode
from ceres.data import (
    FromYAML,
    JSONSerializableDict,
    MaybeSequence,
    NonEmptyStr,
    OrderedStrEnum,
)
from ceres.user import UserRole, UserRow

if TYPE_CHECKING:
    from collections.abc import Iterable

    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres._internal.protocols import DatabaseSource
    from ceres.database import DatabaseType


class WorkspaceAccessLevel(OrderedStrEnum):
    @classmethod
    @override
    def __order_mapping__(cls) -> dict[WorkspaceAccessLevel, int]:
        return {
            cls.ANYONE: UserRole.VIEWER.order,
            cls.OPERATORS: UserRole.OPERATOR.order,
            cls.ADMINS: UserRole.ADMIN.order,
            cls.PRIVATE: UserRole.ADMIN.order + 1,
        }

    ANYONE = "anyone"
    OPERATORS = "operators"
    ADMINS = "admins"
    PRIVATE = "private"


class WorkspaceMembershipRole(OrderedStrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    MANAGER = "manager"


class WorkspaceMembershipRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "workspace_memberships"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper)
    workspace_id: Mapped[UUID] = mapped_column(UUIDMapper)
    role: Mapped[WorkspaceMembershipRole] = mapped_column(EnumMapper(WorkspaceMembershipRole))

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


type WorkspaceMembershipField = Literal[
    "user_id",
    "workspace_id",
    "role",
    "data",
]
type WorkspaceMembershipOrder = Literal[
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


class WorkspaceMembershipCreate(BaseEntityCreate, slots=True):
    user_id: UUID
    workspace_id: UUID
    role: WorkspaceMembershipRole


class WorkspaceMembershipUpdate(TypedDict, total=False):
    role: WorkspaceMembershipRole


class _BaseWorkspaceMembershipQuery(
    BaseEntityQuery[
        "WorkspaceMembership",
        WorkspaceMembershipFilter,
        WorkspaceMembershipUpdate,
        "WorkspaceMembershipQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
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
    __slots__ = ()


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
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, WorkspaceMembership)

    async def get(self, user_id: UUID, workspace_id: UUID, /) -> WorkspaceMembership | None:
        return await self.where(user_id=user_id, workspace_id=workspace_id).first()


class WorkspaceMembership(BaseEntity, WorkspaceMembershipCreate, slots=True):
    Manager = WorkspaceMembershipManager
    Row = WorkspaceMembershipRow
    Create = WorkspaceMembershipCreate
    Update = WorkspaceMembershipUpdate
    Filter = WorkspaceMembershipFilter
    FilterArgs = WorkspaceMembershipFilterArgs
    Field = WorkspaceMembershipField
    Order = WorkspaceMembershipOrder
    Role = WorkspaceMembershipRole

    __naming__: ClassVar[EntityNaming] = EntityNaming("workspace membership")


class WorkspaceEditRow(BaseEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "workspace_edits"

    user_id: Mapped[UUID] = mapped_column(UUIDMapper)
    workspace_id: Mapped[UUID] = mapped_column(UUIDMapper)
    data: Mapped[JSONSerializableDict] = mapped_column(JSON)

    @classmethod
    @override
    def __get_table_args__(cls) -> tuple[SchemaItem, ...]:
        return (
            *super().__get_table_args__(),
            PrimaryKeyConstraint(cls.workspace_id, cls.user_id, name=f"pk_{cls.__tablename__}"),
            ForeignKeyConstraint(
                [cls.workspace_id],
                ["workspaces.id"],
                name=f"fk_{cls.__tablename__}__workspace_id__workspaces__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
            ForeignKeyConstraint(
                [cls.user_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__user_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
        )


type WorkspaceEditField = Literal[
    "user_id",
    "workspace_id",
    "data",
]
type WorkspaceEditOrder = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "workspace_id",
    "workspace_id:asc",
    "workspace_id:desc",
]


class WorkspaceEditFilterArgs(
    BaseEntityFilterArgs[
        WorkspaceEditField,
        WorkspaceEditOrder,
    ],
    total=False,
):
    user_id: MaybeSequence[UUID] | None
    workspace_id: MaybeSequence[UUID] | None


class WorkspaceEditFilter(
    BaseEntityFilter[
        "WorkspaceEdit",
        WorkspaceEditField,
        WorkspaceEditOrder,
    ]
):
    user_id: MaybeSequence[UUID] | None = None
    workspace_id: MaybeSequence[UUID] | None = None

    @classmethod
    @override
    def _get_row_cls(cls) -> type[WorkspaceEditRow]:
        return WorkspaceEditRow

    @override
    def _matches(self, obj: WorkspaceEdit) -> bool:
        if not super()._matches(obj):
            return False

        if not util.match_value(obj.user_id, self.user_id):
            return False
        if not util.match_value(obj.workspace_id, self.workspace_id):
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

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceEditOrder]:
        return "user_id", "workspace_id"


class WorkspaceEditCreate(BaseEntityCreate, slots=True):
    user_id: UUID
    workspace_id: UUID
    data: FromYAML[JSONSerializableDict]


class WorkspaceEditUpdate(BaseEntityUpdate, total=False):
    data: FromYAML[JSONSerializableDict]


class _BaseWorkspaceEditQuery(
    BaseEntityQuery[
        "WorkspaceEdit",
        WorkspaceEditFilter,
        WorkspaceEditUpdate,
        "WorkspaceEditQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
        self,
        filter: WorkspaceEditFilter | None = None,
        **kwargs: Unpack[WorkspaceEditFilterArgs],
    ) -> WorkspaceEditQuery:
        return super().where(filter, **kwargs)

    @override
    def _get_query_class(self) -> type[WorkspaceEditQuery]:
        return WorkspaceEditQuery


class WorkspaceEditQuery(
    EntityQuery[
        "WorkspaceEdit",
        WorkspaceEditFilter,
        WorkspaceEditUpdate,
    ],
    _BaseWorkspaceEditQuery,
):
    __slots__ = ()


class WorkspaceEditManager(
    BaseEntityManager[
        "WorkspaceEdit",
        WorkspaceEditRow,
        WorkspaceEditCreate,
        WorkspaceEditUpdate,
        WorkspaceEditFilter,
        WorkspaceEditFilterArgs,
    ],
    _BaseWorkspaceEditQuery,
):
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, WorkspaceEdit)

    async def get(self, user_id: UUID, workspace_id: UUID, /) -> WorkspaceEdit | None:
        return await self.where(user_id=user_id, workspace_id=workspace_id).first()


class WorkspaceEdit(BaseEntity, WorkspaceEditCreate, slots=True):
    Manager = WorkspaceEditManager
    Row = WorkspaceEditRow
    Create = WorkspaceEditCreate
    Update = WorkspaceEditUpdate
    Filter = WorkspaceEditFilter
    FilterArgs = WorkspaceEditFilterArgs
    Field = WorkspaceEditField
    Order = WorkspaceEditOrder

    __naming__: ClassVar[EntityNaming] = EntityNaming("workspace edit")


def _membership_roles_ge(access: WorkspaceMembershipRole) -> list[WorkspaceMembershipRole]:
    return [current for current in WorkspaceMembershipRole if current >= access]


def _ordered_enum_value[T: OrderedStrEnum](
    enum: type[T],
    value: SQLColumnExpression[T],
) -> SQLColumnExpression[int | None]:
    return case(
        *[
            (
                value == literal_column("'" + current + "'"),
                literal_column(str(current.order), type_=Integer),
            )
            for current in enum
        ],
    )


class WorkspaceRow(BaseUUIDEntityRow, kw_only=True):
    __tablename__: ClassVar[str] = "workspaces"

    name: Mapped[str] = mapped_column(Text)
    general_viewership: Mapped[WorkspaceAccessLevel] = mapped_column(
        EnumMapper(WorkspaceAccessLevel),
        default=WorkspaceAccessLevel.PRIVATE,
        server_default=str(WorkspaceAccessLevel.PRIVATE),
    )
    general_editorship: Mapped[WorkspaceAccessLevel] = mapped_column(
        EnumMapper(WorkspaceAccessLevel),
        default=WorkspaceAccessLevel.PRIVATE,
        server_default=str(WorkspaceAccessLevel.PRIVATE),
    )
    general_managership: Mapped[WorkspaceAccessLevel] = mapped_column(
        EnumMapper(WorkspaceAccessLevel),
        default=WorkspaceAccessLevel.PRIVATE,
        server_default=str(WorkspaceAccessLevel.PRIVATE),
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
                cls.general_viewership,
                WorkspaceAccessLevel,
                name=f"ck_{cls.__tablename__}__general_viewership",
            ),
            EnumConstraint(
                cls.general_editorship,
                WorkspaceAccessLevel,
                name=f"ck_{cls.__tablename__}__general_editorship",
            ),
            EnumConstraint(
                cls.general_managership,
                WorkspaceAccessLevel,
                name=f"ck_{cls.__tablename__}__general_managership",
            ),
        )


type WorkspaceField = (
    BaseUUIDEntityField
    | Literal[
        "name",
        "general_viewership",
        "general_editorship",
        "general_managership",
        "data",
    ]
)
type WorkspaceOrder = (
    BaseUUIDEntityOrder
    | Literal[
        "name",
        "name:asc",
        "name:desc",
        "general_viewership",
        "general_viewership:asc",
        "general_viewership:desc",
        "general_editorship",
        "general_editorship:asc",
        "general_editorship:desc",
        "general_managership",
        "general_managership:asc",
        "general_managership:desc",
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
    general_viewership: MaybeSequence[WorkspaceAccessLevel]
    general_editorship: MaybeSequence[WorkspaceAccessLevel]
    general_managership: MaybeSequence[WorkspaceAccessLevel]
    viewable_by: MaybeSequence[UUID] | None
    editable_by: MaybeSequence[UUID] | None
    manageable_by: MaybeSequence[UUID] | None
    joined_by: MaybeSequence[UUID] | None


class WorkspaceFilter(BaseUUIDEntityFilter["Workspace", WorkspaceField, WorkspaceOrder]):
    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given usernames."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""
    general_viewership: MaybeSequence[WorkspaceAccessLevel] | None = None
    """Filter by `general_viewership` being equal to one or more given access levels."""
    general_editorship: MaybeSequence[WorkspaceAccessLevel] | None = None
    """Filter by `general_editorship` being equal to one or more given access levels."""
    general_managership: MaybeSequence[WorkspaceAccessLevel] | None = None
    """Filter by `general_managership` being equal to one or more given access levels."""
    viewable_by: MaybeSequence[UUID] | None = None
    """Filter, matching only workspaces viewable by one or more given user IDs."""
    editable_by: MaybeSequence[UUID] | None = None
    """Filter, matching only workspaces editable by one or more given user IDs."""
    manageable_by: MaybeSequence[UUID] | None = None
    """Filter, matching only workspaces manageable by one or more given user IDs."""
    joined_by: MaybeSequence[UUID] | None = None
    """Filter, matching only workspaces where on or more given user IDs are members."""

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

        if not util.match_value(obj.general_viewership, self.general_viewership):
            return False
        if not util.match_value(obj.general_editorship, self.general_editorship):
            return False
        if not util.match_value(obj.general_managership, self.general_managership):
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

        if self.general_viewership is not None:
            yield util.sql_match_value(columns.general_viewership, self.general_viewership)
        if self.general_editorship is not None:
            yield util.sql_match_value(columns.general_editorship, self.general_editorship)
        if self.general_managership is not None:
            yield util.sql_match_value(columns.general_managership, self.general_managership)

        for user_id, general_access_restriction, min_membership_role in (
            (self.viewable_by, columns.general_viewership, WorkspaceMembershipRole.VIEWER),
            (self.editable_by, columns.general_editorship, WorkspaceMembershipRole.EDITOR),
            (self.manageable_by, columns.general_managership, WorkspaceMembershipRole.MANAGER),
        ):
            if user_id is None:
                continue

            yield or_(
                *(
                    columns.id.in_(
                        select(columns.id).where(
                            _ordered_enum_value(
                                WorkspaceAccessLevel,
                                general_access_restriction,
                            )
                            <= _ordered_enum_value(
                                UserRole,
                                select(UserRow.role)
                                .where(UserRow.id == current_user_id)
                                .label("role"),
                            )
                        )
                    )
                    for current_user_id in util.seq(user_id)
                )
            ) | (
                columns.id.in_(
                    select(WorkspaceMembershipRow.workspace_id).where(
                        WorkspaceMembershipRow.user_id.in_(util.seq(user_id)),
                        WorkspaceMembershipRow.role.in_(_membership_roles_ge(min_membership_role)),
                    )
                )
            )

        if self.joined_by is not None:
            yield columns.id.in_(
                select(WorkspaceMembershipRow.workspace_id).where(
                    WorkspaceMembershipRow.user_id.in_(util.seq(self.joined_by)),
                )
            )

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceOrder]:
        return "name"


class WorkspaceCreate(BaseUUIDEntityCreate, slots=True):
    name: NonEmptyStr
    general_viewership: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    general_editorship: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    general_managership: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    data: FromYAML[JSONSerializableDict] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        general_editorship_restriction = (
            self.general_editorship.order if self.general_editorship is not None else -1
        )
        general_viewership_value = (
            self.general_viewership.order if self.general_viewership is not None else -1
        )
        general_managership_restriction = (
            self.general_managership.order if self.general_managership is not None else -1
        )
        if general_editorship_restriction < general_viewership_value:
            raise ValueError(
                "`general_editorship` must be as or more restrictive than `general_viewership`"
            )
        if general_managership_restriction < general_editorship_restriction:
            raise ValueError(
                "`general_managership` must be as or more restrictive than `general_editorship`"
            )

        return self


class WorkspaceUpdate(TypedDict, total=False):
    name: NonEmptyStr
    general_viewership: WorkspaceAccessLevel
    general_editorship: WorkspaceAccessLevel
    general_managership: WorkspaceAccessLevel
    data: FromYAML[JSONSerializableDict]


class _BaseWorkspaceQuery(
    BaseEntityQuery[
        "Workspace",
        WorkspaceFilter,
        WorkspaceUpdate,
        "WorkspaceQuery",
    ]
):
    __slots__ = ()

    @override
    def where(  # type: ignore
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
    __slots__ = ()


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
    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Workspace)

    async def get(self, id: UUID, /) -> Workspace | None:
        return await self.where(id=id).first()


class Workspace(BaseUUIDEntity, WorkspaceCreate, slots=True):
    Manager = WorkspaceManager
    Row = WorkspaceRow
    Create = WorkspaceCreate
    Update = WorkspaceUpdate
    Filter = WorkspaceFilter
    FilterArgs = WorkspaceFilterArgs
    Field = WorkspaceField
    Order = WorkspaceOrder

    Edit = WorkspaceEdit
    Membership = WorkspaceMembership

    __naming__: ClassVar[EntityNaming] = EntityNaming("workspace")
