from __future__ import annotations

from ceres._internal.typedecs import __Entity__
from ceres.data import StrEnum


class EntityType(StrEnum):
    MESSAGE = "message"
    PARTICLE = "particle"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    USER = "user"
    VARIABLE = "variable"
    SETTING = "setting"

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

    @property
    def cls(self) -> type[__Entity__]:
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


def __new_override(cls: type[EntityType], alias: str) -> EntityType:
    return cls(__ENTITY_TYPE_ALIASES.get(alias, alias))


__new_override.__name__ = "__new__"

EntityType.__new__ = __new_override  # type: ignore
