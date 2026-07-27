from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Literal, Self, TypedDict, Unpack, override
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKeyConstraint,
    PrimaryKeyConstraint,
    Text,
    false,
    select,
)
from sqlalchemy.orm import Mapped, mapped_column

from ceres.__internal__.database.types import AddressMapper, EnumConstraint, EnumMapper, UUIDMapper
from ceres.__internal__.entity import (
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
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.utilities.collections import seq
from ceres.address import Address
from ceres.data import FromYAML, JSONSerializableDict, MaybeSequence, NonEmptyStr, OrderedStrEnum
from ceres.user import UserRow

if TYPE_CHECKING:
    from sqlalchemy import SQLColumnExpression
    from sqlalchemy.schema import SchemaItem

    from ceres.__internal__.protocols import DatabaseSource
    from ceres.database import DatabaseType

__all__ = [
    "Workspace",
    "WorkspaceEdit",
    "WorkspaceMembership",
]


class WorkspaceAccessLevel(OrderedStrEnum):
    """General access level required for a user to gain a capability on a workspace.

    A workspace sets one of these levels for viewership, editorship, and managership. `ANYONE`
    grants the capability to any authenticated user, `PRIVATE` requires an explicit membership.
    Admin users bypass general access restrictions entirely.
    """

    @classmethod
    @override
    def __order_mapping__(cls) -> dict[WorkspaceAccessLevel, int]:
        return {
            cls.ANYONE: 0,
            cls.PRIVATE: 1,
        }

    ANYONE = "anyone"
    """Any authenticated user qualifies."""
    PRIVATE = "private"
    """No one qualifies via general access, explicit membership is required."""


class WorkspaceMembershipRole(OrderedStrEnum):
    """Role a user holds within a specific workspace, granted by a `WorkspaceMembership`."""

    VIEWER = "viewer"
    """Read-only access to the workspace."""
    EDITOR = "editor"
    """Read and write access to the workspace's contents."""
    MANAGER = "manager"
    """Full access, including management of memberships and workspace settings."""


class WorkspaceMembershipRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `WorkspaceMembership` entity."""

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
]
"""Field names selectable in `WorkspaceMembership` queries."""

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
"""Ordering keys accepted by `WorkspaceMembership` queries."""


class WorkspaceMembershipFilterArgs(
    BaseEntityFilterArgs[
        WorkspaceMembershipField,
        WorkspaceMembershipOrder,
    ],
    total=False,
):
    """Keyword-argument form of `WorkspaceMembershipFilter` for ergonomic call sites."""

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
    """Filter for selecting `WorkspaceMembership` records by user, workspace, or role."""

    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given user IDs."""
    workspace_id: MaybeSequence[UUID] | None = None
    """Filter by `workspace_id` being equal to one or more given workspace IDs."""
    role: MaybeSequence[WorkspaceMembershipRole] | None = None
    """Filter by `role` being equal to one or more given roles."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[WorkspaceMembershipRow]:
        return WorkspaceMembershipRow

    @override
    def _matches(self, obj: WorkspaceMembership) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.user_id, self.user_id):
            return False
        if not self._match_value(obj.workspace_id, self.workspace_id):
            return False
        if not self._match_value(obj.role, self.role):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield self._sql_match_value(columns.user_id, self.user_id)
        if self.workspace_id is not None:
            yield self._sql_match_value(columns.workspace_id, self.workspace_id)
        if self.role is not None:
            yield self._sql_match_value(columns.role, self.role)

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceMembershipOrder]:
        return "user_id", "workspace_id"


class WorkspaceMembershipCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `WorkspaceMembership` record."""

    user_id: UUID
    """ID of the user being added to the workspace."""
    workspace_id: UUID
    """ID of the workspace the user is joining."""
    role: WorkspaceMembershipRole
    """Role granted to the user within the workspace."""


class WorkspaceMembershipUpdate(TypedDict, total=False):
    """Partial update for an existing `WorkspaceMembership` record."""

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
    """Query builder for `WorkspaceMembership` records."""

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
    """Database-bound manager for `WorkspaceMembership` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, WorkspaceMembership)

    async def get(self, user_id: UUID, workspace_id: UUID, /) -> WorkspaceMembership | None:
        """Fetch the membership linking a user and workspace, if one exists.

        Args:
            user_id: UUID of the user.
            workspace_id: UUID of the workspace.

        Returns:
            The matching membership, or `None` if the user is not a member of the workspace.
        """
        return await self.where(user_id=user_id, workspace_id=workspace_id).first()


class WorkspaceMembership(
    WorkspaceMembershipCreate,
    ConcreteEntity[WorkspaceMembershipRow],
    slots=True,
):
    """Association record linking a `User` to a `Workspace` with a specific role."""

    Manager = WorkspaceMembershipManager
    Create = WorkspaceMembershipCreate
    Update = WorkspaceMembershipUpdate
    Filter = WorkspaceMembershipFilter
    FilterArgs = WorkspaceMembershipFilterArgs
    Field = WorkspaceMembershipField
    Order = WorkspaceMembershipOrder
    Role = WorkspaceMembershipRole

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("workspace membership")


class WorkspaceEditRow(BaseEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `WorkspaceEdit` entity."""

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
"""Field names selectable in `WorkspaceEdit` queries."""

type WorkspaceEditOrder = Literal[
    "user_id",
    "user_id:asc",
    "user_id:desc",
    "workspace_id",
    "workspace_id:asc",
    "workspace_id:desc",
]
"""Ordering keys accepted by `WorkspaceEdit` queries."""


class WorkspaceEditFilterArgs(
    BaseEntityFilterArgs[
        WorkspaceEditField,
        WorkspaceEditOrder,
    ],
    total=False,
):
    """Keyword-argument form of `WorkspaceEditFilter` for ergonomic call sites."""

    user_id: MaybeSequence[UUID] | None
    workspace_id: MaybeSequence[UUID] | None


class WorkspaceEditFilter(
    BaseEntityFilter[
        "WorkspaceEdit",
        WorkspaceEditField,
        WorkspaceEditOrder,
    ]
):
    """Filter for selecting `WorkspaceEdit` records by user or workspace."""

    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given user IDs."""
    workspace_id: MaybeSequence[UUID] | None = None
    """Filter by `workspace_id` being equal to one or more given workspace IDs."""

    @classmethod
    @override
    def _get_row_cls(cls) -> type[WorkspaceEditRow]:
        return WorkspaceEditRow

    @override
    def _matches(self, obj: WorkspaceEdit) -> bool:
        if not super()._matches(obj):
            return False

        if not self._match_value(obj.user_id, self.user_id):
            return False
        if not self._match_value(obj.workspace_id, self.workspace_id):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.user_id is not None:
            yield self._sql_match_value(columns.user_id, self.user_id)
        if self.workspace_id is not None:
            yield self._sql_match_value(columns.workspace_id, self.workspace_id)

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceEditOrder]:
        return "user_id", "workspace_id"


class WorkspaceEditCreate(BaseEntityCreate, slots=True):
    """Payload for creating a new `WorkspaceEdit` record."""

    user_id: UUID
    """ID of the user whose draft edit this is."""
    workspace_id: UUID
    """ID of the workspace being edited."""
    data: FromYAML[JSONSerializableDict]
    """In-progress edit payload, serialized as JSON."""


class WorkspaceEditUpdate(BaseEntityUpdate, total=False):
    """Partial update for an existing `WorkspaceEdit` record."""

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
    """Query builder for `WorkspaceEdit` records."""

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
    """Database-bound manager for `WorkspaceEdit` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, WorkspaceEdit)

    async def get(self, user_id: UUID, workspace_id: UUID, /) -> WorkspaceEdit | None:
        """Fetch the in-progress edit for a user on a workspace, if one exists.

        Args:
            user_id: UUID of the user whose draft is being fetched.
            workspace_id: UUID of the workspace being edited.

        Returns:
            The matching edit, or `None` if the user has no active edit on the workspace.
        """
        return await self.where(user_id=user_id, workspace_id=workspace_id).first()


class WorkspaceEdit(
    WorkspaceEditCreate,
    ConcreteEntity[WorkspaceEditRow],
    slots=True,
):
    """In-progress edit of a `Workspace` owned by a single user."""

    Manager = WorkspaceEditManager
    Create = WorkspaceEditCreate
    Update = WorkspaceEditUpdate
    Filter = WorkspaceEditFilter
    FilterArgs = WorkspaceEditFilterArgs
    Field = WorkspaceEditField
    Order = WorkspaceEditOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("workspace edit")


def _membership_roles_ge(access: WorkspaceMembershipRole) -> list[WorkspaceMembershipRole]:
    return [current for current in WorkspaceMembershipRole if current >= access]


class WorkspaceRow(BaseUUIDEntityRow, kw_only=True):
    """SQLAlchemy row type backing the `Workspace` entity."""

    __tablename__: ClassVar[str] = "workspaces"

    name: Mapped[str] = mapped_column(Text)
    scope: Mapped[Address] = mapped_column(
        AddressMapper,
        default=Address("~"),
        server_default="~",
    )
    """Address this workspace is placed on. `~` is the engine root, anything else a component."""
    owner_id: Mapped[UUID | None] = mapped_column(UUIDMapper, nullable=True, default=None)
    """Owning user when this workspace is private, `None` when it is shared."""
    show_when_logged_out: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
    )
    """Whether this workspace is part of the set an unauthenticated visitor sees."""
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
            ForeignKeyConstraint(
                [cls.owner_id],
                [UserRow.id],
                name=f"fk_{cls.__tablename__}__owner_id__users__id",
                ondelete="CASCADE",
                onupdate="CASCADE",
            ),
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
        "scope",
        "owner_id",
        "show_when_logged_out",
        "general_viewership",
        "general_editorship",
        "general_managership",
        "data",
    ]
)
"""Field names selectable in `Workspace` queries."""

type WorkspaceOrder = (
    BaseUUIDEntityOrder
    | Literal[
        "name",
        "name:asc",
        "name:desc",
        "scope",
        "scope:asc",
        "scope:desc",
        "owner_id",
        "owner_id:asc",
        "owner_id:desc",
        "show_when_logged_out",
        "show_when_logged_out:asc",
        "show_when_logged_out:desc",
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
"""Ordering keys accepted by `Workspace` queries."""


class WorkspaceFilterArgs(BaseUUIDEntityFilterArgs[WorkspaceField, WorkspaceOrder], total=False):
    """Keyword-argument form of `WorkspaceFilter` for ergonomic call sites."""

    name: MaybeSequence[str] | None
    name_contains: MaybeSequence[str] | None
    name_prefix: MaybeSequence[str] | None
    name_suffix: MaybeSequence[str] | None
    scope: MaybeSequence[Address] | None
    placed_on_engine: bool | None
    owner_id: MaybeSequence[UUID] | None
    owned: bool | None
    show_when_logged_out: bool | None
    general_viewership: MaybeSequence[WorkspaceAccessLevel]
    general_editorship: MaybeSequence[WorkspaceAccessLevel]
    general_managership: MaybeSequence[WorkspaceAccessLevel]
    viewable_by: MaybeSequence[UUID] | None
    editable_by: MaybeSequence[UUID] | None
    manageable_by: MaybeSequence[UUID] | None
    joined_by: MaybeSequence[UUID] | None


class WorkspaceFilter(BaseUUIDEntityFilter["Workspace", WorkspaceField, WorkspaceOrder]):
    """Filter for selecting `Workspace` records by name, access settings, or user access."""

    name: MaybeSequence[str] | None = None
    """Filter by `name` being equal to one or more given usernames."""
    name_contains: MaybeSequence[str] | None = None
    """Filter by `name` containing one or more given substrings."""
    name_prefix: MaybeSequence[str] | None = None
    """Filter by `name` starting with one or more given prefixes."""
    name_suffix: MaybeSequence[str] | None = None
    """Filter by `name` ending with one or more given suffixes."""
    scope: MaybeSequence[Address] | None = None
    """Filter by `scope` being equal to one or more given placement addresses."""
    placed_on_engine: bool | None = None
    """Filter by whether the workspace is placed on the engine root rather than a component."""
    owner_id: MaybeSequence[UUID] | None = None
    """Filter by `owner_id` being equal to one or more given user IDs."""
    owned: bool | None = None
    """Filter by whether the workspace is private to an owner at all."""
    show_when_logged_out: bool | None = None
    """Filter by whether the workspace is shown to unauthenticated visitors."""
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

        if not self._match_value(obj.name, self.name):
            return False
        if not self._match_string_contains(obj.name, self.name_contains):
            return False
        if not self._match_string_prefix(obj.name, self.name_prefix):
            return False
        if not self._match_string_suffix(obj.name, self.name_suffix):
            return False

        if not self._match_value(obj.scope, self.scope):
            return False
        if self.placed_on_engine is not None and obj.scope.is_engine != self.placed_on_engine:
            return False

        if not self._match_value(obj.owner_id, self.owner_id):
            return False
        if self.owned is not None and (obj.owner_id is not None) != self.owned:
            return False
        if (
            self.show_when_logged_out is not None
            and obj.show_when_logged_out != self.show_when_logged_out
        ):
            return False

        if not self._match_value(obj.general_viewership, self.general_viewership):
            return False
        if not self._match_value(obj.general_editorship, self.general_editorship):
            return False
        if not self._match_value(obj.general_managership, self.general_managership):
            return False

        return True

    @override
    def _get_where(self, dialect: DatabaseType) -> Iterable[SQLColumnExpression[bool]]:
        yield from super()._get_where(dialect)
        columns = self._get_row_cls()

        if self.name is not None:
            yield self._sql_match_value(columns.name, self.name)
        if self.name_contains is not None:
            yield self._sql_match_string_contains(columns.name, self.name_contains)
        if self.name_prefix is not None:
            yield self._sql_match_string_prefix(columns.name, self.name_prefix)
        if self.name_suffix is not None:
            yield self._sql_match_string_suffix(columns.name, self.name_suffix)

        if self.scope is not None:
            yield self._sql_match_value(columns.scope, self.scope)
        if self.placed_on_engine is not None:
            on_engine = columns.scope == Address("~")
            yield on_engine if self.placed_on_engine else ~on_engine

        if self.owner_id is not None:
            yield self._sql_match_value(columns.owner_id, self.owner_id)
        if self.owned is not None:
            yield columns.owner_id.is_not(None) if self.owned else columns.owner_id.is_(None)
        if self.show_when_logged_out is not None:
            yield columns.show_when_logged_out == self.show_when_logged_out

        if self.general_viewership is not None:
            yield self._sql_match_value(columns.general_viewership, self.general_viewership)
        if self.general_editorship is not None:
            yield self._sql_match_value(columns.general_editorship, self.general_editorship)
        if self.general_managership is not None:
            yield self._sql_match_value(columns.general_managership, self.general_managership)

        for user_id, general_access_restriction, min_membership_role in (
            (self.viewable_by, columns.general_viewership, WorkspaceMembershipRole.VIEWER),
            (self.editable_by, columns.general_editorship, WorkspaceMembershipRole.EDITOR),
            (self.manageable_by, columns.general_managership, WorkspaceMembershipRole.MANAGER),
        ):
            if user_id is None:
                continue

            yield (general_access_restriction == WorkspaceAccessLevel.ANYONE) | (
                columns.id.in_(
                    select(WorkspaceMembershipRow.workspace_id).where(
                        WorkspaceMembershipRow.user_id.in_(seq(user_id)),
                        WorkspaceMembershipRow.role.in_(_membership_roles_ge(min_membership_role)),
                    )
                )
            )

        if self.joined_by is not None:
            yield columns.id.in_(
                select(WorkspaceMembershipRow.workspace_id).where(
                    WorkspaceMembershipRow.user_id.in_(seq(self.joined_by)),
                )
            )

    @override
    def _get_default_order(self) -> MaybeSequence[WorkspaceOrder]:
        return "name"


class WorkspaceCreate(BaseUUIDEntityCreate, slots=True):
    """Payload for creating a new `Workspace` record.

    The three general access fields must be ordered from least to most restrictive, viewership must
    be at least as permissive as editorship, which must be at least as permissive as managership.
    Creation fails with a validation error if that invariant is violated.
    """

    name: NonEmptyStr
    """Human-readable name of the workspace."""
    scope: Address = Address("~")
    """Address this workspace is placed on. `~` is the engine root, anything else a component."""
    owner_id: UUID | None = None
    """Owning user when this workspace is private, `None` when it is shared."""
    show_when_logged_out: bool = False
    """Whether this workspace is part of the set an unauthenticated visitor sees."""
    general_viewership: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    """General access level required to view the workspace without an explicit membership."""
    general_editorship: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    """General access level required to edit the workspace without an explicit membership."""
    general_managership: WorkspaceAccessLevel = WorkspaceAccessLevel.PRIVATE
    """General access level required to manage the workspace without an explicit membership."""
    data: FromYAML[JSONSerializableDict] = Field(default_factory=dict)
    """Free-form structured payload attached to the workspace."""

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
    """Partial update for an existing `Workspace` record."""

    name: NonEmptyStr
    scope: Address
    owner_id: UUID | None
    show_when_logged_out: bool
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
    """Query builder for `Workspace` records."""

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
    """Database-bound manager for `Workspace` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Workspace)

    async def get(self, id: UUID, /) -> Workspace | None:
        """Fetch a single workspace by its identifier.

        Args:
            id: UUID of the workspace to fetch.

        Returns:
            The matching workspace, or `None` if no workspace with that id exists.
        """
        return await self.where(id=id).first()


class Workspace(
    BaseUUIDEntity,
    WorkspaceCreate,
    ConcreteEntity[WorkspaceRow],
    slots=True,
):
    """Named collection that groups users and content under shared access-control settings.

    Access to a workspace is granted in two ways: general access, where any authenticated user
    automatically gains a capability whose `general_*` level is set to
    `WorkspaceAccessLevel.ANYONE`, and explicit `WorkspaceMembership`, which grants a specific
    `role` to a single user.
    """

    Manager = WorkspaceManager
    Create = WorkspaceCreate
    Update = WorkspaceUpdate
    Filter = WorkspaceFilter
    FilterArgs = WorkspaceFilterArgs
    Field = WorkspaceField
    Order = WorkspaceOrder

    Edit = WorkspaceEdit
    Membership = WorkspaceMembership

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("workspace")
