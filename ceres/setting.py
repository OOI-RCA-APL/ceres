from typing import TYPE_CHECKING, ClassVar, Unpack, override

from ceres.__internal__.entity import (
    BaseEntityManager,
    BaseEntityQuery,
    ConcreteEntity,
    EntityNaming,
    EntityQuery,
)
from ceres.__internal__.manager import BaseNodeManager
from ceres.__internal__.models.settings import (
    SettingCreate,
    SettingField,
    SettingFilter,
    SettingFilterArgs,
    SettingOrder,
    SettingUpdate,
)

if TYPE_CHECKING:
    from uuid import UUID

    from ceres.__internal__.protocols import DatabaseSource, NodeSource

__all__ = [
    "Setting",
    "SettingField",
    "SettingOrder",
    "SettingFilterArgs",
    "SettingFilter",
    "SettingCreate",
    "SettingUpdate",
    "SettingManager",
    "BoundSettingManager",
]


class _BaseSettingQuery(
    BaseEntityQuery[
        "Setting",
        SettingFilter,
        SettingUpdate,
        "SettingQuery",
    ]
):
    __slots__ = ()

    @override
    def _get_query_class(self) -> type[SettingQuery]:
        return SettingQuery

    @override
    def where(  # type: ignore
        self,
        filter: SettingFilter | None = None,
        **kwargs: Unpack[SettingFilterArgs],
    ) -> SettingQuery:
        return super().where(filter, **kwargs)


class SettingQuery(
    EntityQuery[
        "Setting",
        SettingFilter,
        SettingUpdate,
    ],
    _BaseSettingQuery,
):
    """Query builder for `Setting` records."""

    __slots__ = ()


class SettingManager(
    BaseEntityManager[
        "Setting",
        SettingCreate,
        SettingUpdate,
        SettingFilter,
        SettingFilterArgs,
    ],
    _BaseSettingQuery,
):
    """Database-bound manager for `Setting` records."""

    __slots__ = ()

    def __init__(self, source: DatabaseSource, /) -> None:
        super().__init__(source, Setting)

    async def get(self, user_id: UUID, name: str, /) -> Setting | None:
        """Fetch a single setting by its composite key.

        Args:
            user_id: Identifier of the user that owns the setting.
            name: Name of the setting.

        Returns:
            The matching setting, or `None` if no setting with that key exists.
        """
        return await self.where(user_id=user_id, name=name).first()


class BoundSettingManager(SettingManager, BaseNodeManager):
    """Component-bound setting manager exposed to nodes."""

    __slots__ = ()

    def __init__(self, source: NodeSource, /) -> None:
        super().__init__(source)


class Setting(SettingCreate, ConcreteEntity, slots=True):
    """Per-user named value used to persist user preferences and application state.

    Settings are keyed by `(user_id, name)` and store arbitrary JSON-serializable values.
    """

    Manager = SettingManager
    BoundManager = BoundSettingManager
    Create = SettingCreate
    Update = SettingUpdate
    Filter = SettingFilter
    FilterArgs = SettingFilterArgs
    Field = SettingField
    Order = SettingOrder

    __entity_naming__: ClassVar[EntityNaming] = EntityNaming("setting")
