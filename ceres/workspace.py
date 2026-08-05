from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, override
from uuid import UUID

from pydantic import Field

from ceres.__internal__.entity import (
    BaseEntityCreate,
    BaseEntityFilter,
    BaseEntityFilterArgs,
    BaseEntityManager,
    BaseEntityQuery,
    BaseEntityUpdate,
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
from ceres.address import Address
from ceres.data import FromYAML, JSONSerializableDict, MaybeSequence, NonEmptyStr

if TYPE_CHECKING:
    from ceres.__internal__.protocols import DatabaseSource

__all__ = [
    "Workspace",
    "WorkspaceEdit",
]


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

    __table__: ClassVar[str] = "workspace_edits"

    user_id: MaybeSequence[UUID] | None = None
    """Filter by `user_id` being equal to one or more given user IDs."""
    workspace_id: MaybeSequence[UUID] | None = None
    """Filter by `workspace_id` being equal to one or more given workspace IDs."""


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
    ConcreteEntity,
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


type WorkspaceField = (
    BaseUUIDEntityField
    | Literal[
        "name",
        "scope",
        "owner_id",
        "show_when_logged_out",
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


class WorkspaceFilter(BaseUUIDEntityFilter["Workspace", WorkspaceField, WorkspaceOrder]):
    """Filter for selecting `Workspace` records by name, access settings, or user access."""

    __table__: ClassVar[str] = "workspaces"

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


class WorkspaceCreate(BaseUUIDEntityCreate, slots=True):
    """Payload for creating a new `Workspace` record."""

    name: NonEmptyStr
    """Human-readable name of the workspace."""
    scope: Address = Address("~")
    """Address this workspace is placed on. `~` is the engine root, anything else a component."""
    owner_id: UUID | None = None
    """Owning user when this workspace is private, `None` when it is shared."""
    show_when_logged_out: bool = False
    """Whether this workspace is part of the set an unauthenticated visitor sees."""
    data: FromYAML[JSONSerializableDict] = Field(default_factory=dict)
    """Free-form structured payload attached to the workspace."""


class WorkspaceUpdate(TypedDict, total=False):
    """Partial update for an existing `Workspace` record."""

    name: NonEmptyStr
    scope: Address
    owner_id: UUID | None
    show_when_logged_out: bool
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
    ConcreteEntity,
    slots=True,
):
    """Named arrangement of widgets, placed on a component or on the engine root.

    A workspace has no access settings of its own. It inherits them from its placement, so
    whoever can view a component can view the workspaces placed on it, and whoever can manage
    that component can edit them. Setting `owner_id` makes a workspace private to one user, who
    is then the only person who can see or change it.
    """

    Manager = WorkspaceManager
    Create = WorkspaceCreate
    Update = WorkspaceUpdate
    Filter = WorkspaceFilter
    FilterArgs = WorkspaceFilterArgs
    Field = WorkspaceField
    Order = WorkspaceOrder

    Edit = WorkspaceEdit

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("workspace")
