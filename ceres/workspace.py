from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    BaseUUIDEntity,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.models.workspaces import (
    WorkspaceCreate,
    WorkspaceEditCreate,
    WorkspaceEditField,
    WorkspaceEditFilter,
    WorkspaceEditFilterArgs,
    WorkspaceEditOrder,
    WorkspaceEditUpdate,
    WorkspaceField,
    WorkspaceFilter,
    WorkspaceFilterArgs,
    WorkspaceOrder,
    WorkspaceUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource

__all__ = [
    "Workspace",
    "WorkspaceEdit",
]


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
