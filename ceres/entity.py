# ruff: noqa: TC001


import sys
from functools import wraps
from typing import TYPE_CHECKING, TypeAlias

from ceres.__internal__.lazy import __lazy_imports__
from ceres.data import StrEnum

with __lazy_imports__(__name__, export=True):
    from ceres.alert import Alert as Alert
    from ceres.group import Group as Group
    from ceres.group import GroupMembership as GroupMembership
    from ceres.logs import LogEntry as LogEntry
    from ceres.message import Message as Message
    from ceres.particle import Particle as Particle
    from ceres.permission import GroupPermission as GroupPermission
    from ceres.permission import UserPermission as UserPermission
    from ceres.setting import Setting as Setting
    from ceres.user import User as User
    from ceres.variable import Variable as Variable
    from ceres.workspace import Workspace as Workspace
    from ceres.workspace import WorkspaceEdit as WorkspaceEdit

__all__ = [
    "Entity",
    "EntityType",
]

# Lazy cache for the `Entity` union type, the runtime value is built on first access to avoid
# importing every entity submodule at import time.
_Entity: object = None

if TYPE_CHECKING:
    Entity: TypeAlias = (
        Message
        | Particle
        | Alert
        | LogEntry
        | User
        | Variable
        | Setting
        | Workspace
        | WorkspaceEdit
        | Group
        | GroupMembership
        | UserPermission
        | GroupPermission
    )
    """Union of every persistent entity managed by the engine.

    Entities cover the full set of records and configuration objects the engine stores, use
    `Record` instead when only time-series outputs are needed.
    """

_lazy_getattr = sys.modules[__name__].__getattr__


def __getattr__(name: str):
    global _Entity

    # Resolve the runtime `Entity` union lazily so that importing `ceres.entity` does not force
    # the import of every entity submodule.
    if name == "Entity":
        if _Entity is None:
            from ceres.alert import Alert
            from ceres.group import Group, GroupMembership
            from ceres.logs import LogEntry
            from ceres.message import Message
            from ceres.particle import Particle
            from ceres.permission import GroupPermission, UserPermission
            from ceres.setting import Setting
            from ceres.user import User
            from ceres.variable import Variable
            from ceres.workspace import Workspace, WorkspaceEdit

            _Entity = (
                Message
                | Particle
                | Alert
                | LogEntry
                | User
                | Variable
                | Setting
                | Workspace
                | WorkspaceEdit
                | Group
                | GroupMembership
                | UserPermission
                | GroupPermission
            )

        return _Entity

    return _lazy_getattr(name)


class EntityType(StrEnum):
    """Discriminator naming each variant of `Entity`.

    The string values double as the canonical entity name in URLs, configuration files, and
    stored records. Aliases such as plural forms are accepted via `__new__`.
    """

    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    USER = "user"
    VARIABLE = "variable"
    SETTING = "setting"
    WORKSPACE = "workspace"
    WORKSPACE_EDIT = "workspace-edit"
    GROUP = "group"
    GROUP_MEMBERSHIP = "group-membership"
    USER_PERMISSION = "user-permission"
    GROUP_PERMISSION = "group-permission"

    @property
    def cls(self) -> type[Entity]:
        """Return the concrete entity class associated with this variant.

        Returns:
            The `Entity` subclass matching this enum value.

        Raises:
            ValueError: If the enum value has no associated class, this should be unreachable
                for valid `EntityType` members.
        """
        # Imports are deferred inside each branch to avoid circular imports between this module
        # and the individual entity modules.
        match self:
            case EntityType.MESSAGE:
                from ceres.message import Message

                return Message
            case EntityType.PARTICLE:
                from ceres.particle import Particle

                return Particle
            case EntityType.ALERT:
                from ceres.alert import Alert

                return Alert
            case EntityType.LOG_ENTRY:
                from ceres.logs import LogEntry

                return LogEntry
            case EntityType.USER:
                from ceres.user import User

                return User
            case EntityType.VARIABLE:
                from ceres.variable import Variable

                return Variable
            case EntityType.SETTING:
                from ceres.setting import Setting

                return Setting
            case EntityType.WORKSPACE:
                from ceres.workspace import Workspace

                return Workspace
            case EntityType.WORKSPACE_EDIT:
                from ceres.workspace import WorkspaceEdit

                return WorkspaceEdit
            case EntityType.GROUP:
                from ceres.group import Group

                return Group
            case EntityType.GROUP_MEMBERSHIP:
                from ceres.group import GroupMembership

                return GroupMembership
            case EntityType.USER_PERMISSION:
                from ceres.permission import UserPermission

                return UserPermission
            case EntityType.GROUP_PERMISSION:
                from ceres.permission import GroupPermission

                return GroupPermission

        raise ValueError(self)

    @classmethod
    def from_class(cls, source: type[Entity], /) -> EntityType:
        """Return the `EntityType` matching an entity class.

        Args:
            source: An entity class such as `Message` or `Particle`.

        Returns:
            The `EntityType` member that corresponds to `source`.

        Raises:
            ValueError: If `source` is not one of the recognized entity classes.
        """
        match source.__name__:
            case "Message":
                return cls.MESSAGE
            case "Particle":
                return cls.PARTICLE
            case "Alert":
                return cls.ALERT
            case "LogEntry":
                return cls.LOG_ENTRY
            case "User":
                return cls.USER
            case "Variable":
                return cls.VARIABLE
            case "Setting":
                return cls.SETTING
            case "Workspace":
                return cls.WORKSPACE
            case "WorkspaceEdit":
                return cls.WORKSPACE_EDIT
            case "Group":
                return cls.GROUP
            case "GroupMembership":
                return cls.GROUP_MEMBERSHIP
            case "UserPermission":
                return cls.USER_PERMISSION
            case "GroupPermission":
                return cls.GROUP_PERMISSION
            case _:
                raise ValueError(f"Unknown entity type: {source}")


# Plural and alternate spellings accepted when constructing an `EntityType` from a string, this
# keeps configuration files and URLs forgiving.
_ENTITY_TYPE_ALIASES = {
    "messages": "message",
    "particles": "particle",
    "alerts": "alert",
    "log-entries": "log-entry",
    "logs": "log-entry",
    "users": "user",
    "variables": "variable",
    "settings": "setting",
    "workspaces": "workspace",
    "workspace-edits": "workspace-edit",
    "groups": "group",
    "group-memberships": "group-membership",
    "user-permissions": "user-permission",
    "group-permissions": "group-permission",
}

_base__new__ = EntityType.__new__


@wraps(_base__new__)
def _override__new__(cls: type[EntityType], value: str) -> EntityType:
    # Pass through existing instances unchanged so that `EntityType(EntityType.MESSAGE)` does
    # not need to round-trip through string conversion.
    if isinstance(value, EntityType):
        return value

    return _base__new__(cls, _ENTITY_TYPE_ALIASES.get(value, value))


EntityType.__new__ = _override__new__
