from __future__ import annotations

import sys
from functools import wraps
from typing import TYPE_CHECKING, TypeAlias

from ceres._internal.lazy import lazy_imports
from ceres.data import StrEnum

with lazy_imports(__name__, export=True):
    from ceres.alert import Alert as Alert
    from ceres.logs import LogEntry as LogEntry
    from ceres.message import Message as Message
    from ceres.particle import Particle as Particle
    from ceres.setting import Setting as Setting
    from ceres.user import User as User
    from ceres.variable import Variable as Variable

__Entity: object = None

if TYPE_CHECKING:
    Entity: TypeAlias = Message | Particle | Alert | LogEntry | User | Variable | Setting

__lazy_getattr = sys.modules[__name__].__getattr__


def __getattr__(name: str):
    global __Entity

    if name == "Entity":
        if __Entity is None:
            from ceres.alert import Alert
            from ceres.logs import LogEntry
            from ceres.message import Message
            from ceres.particle import Particle
            from ceres.setting import Setting
            from ceres.user import User
            from ceres.variable import Variable

            __Entity = Message | Particle | Alert | LogEntry | User | Variable | Setting

        return __Entity

    return __lazy_getattr(name)


class EntityType(StrEnum):
    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    USER = "user"
    VARIABLE = "variable"
    SETTING = "setting"

    @property
    def cls(self) -> type[Entity]:
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

        raise ValueError(self)

    @classmethod
    def from_class(cls, source: type[Entity], /) -> EntityType:
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
            case _:
                raise ValueError(f"Unknown entity type: {source}")

    @property
    def table(self) -> str:
        match self:
            case EntityType.MESSAGE:
                return "messages"
            case EntityType.PARTICLE:
                return "particles"
            case EntityType.ALERT:
                return "alerts"
            case EntityType.LOG_ENTRY:
                return "logs"
            case EntityType.USER:
                return "users"
            case EntityType.VARIABLE:
                return "variables"
            case EntityType.SETTING:
                return "settings"

        raise ValueError(self)


__ENTITY_TYPE_ALIASES = {
    "messages": "message",
    "particles": "particle",
    "alerts": "alert",
    "log-entries": "log-entry",
    "logs": "log-entry",
    "users": "user",
    "variables": "variable",
    "settings": "setting",
}

__new = EntityType.__new__


@wraps(__new)
def __new_override(cls: type[EntityType], value: str) -> EntityType:
    if isinstance(value, EntityType):
        return value

    return __new(cls, __ENTITY_TYPE_ALIASES.get(value, value))


EntityType.__new__ = __new_override  # type: ignore
