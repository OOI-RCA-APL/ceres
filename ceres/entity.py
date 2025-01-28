from __future__ import annotations

from functools import wraps
from typing import TypeAlias

from ceres.alert import Alert as Alert
from ceres.data import StrEnum
from ceres.logs import LogEntry as LogEntry
from ceres.message import Message as Message
from ceres.particle import Particle as Particle
from ceres.setting import Setting as Setting
from ceres.user import User as User
from ceres.variable import Variable as Variable

Entity: TypeAlias = Alert | LogEntry | Message | User | Variable | Particle | Setting


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
                return Message
            case EntityType.PARTICLE:
                return Particle
            case EntityType.ALERT:
                return Alert
            case EntityType.LOG_ENTRY:
                return LogEntry
            case EntityType.USER:
                return User
            case EntityType.VARIABLE:
                return Variable
            case EntityType.SETTING:
                return Setting

        raise ValueError(self)

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
                return "log_entries"
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
