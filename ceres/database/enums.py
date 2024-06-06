from __future__ import annotations

from ceres._internal.lazy import lazy_imports
from ceres.data import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"


with lazy_imports(__name__):
    from ceres.entity import BaseEntity


class EntityType(StrEnum):
    MESSAGE = "message"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    USER = "user"
    STORE = "store"

    @property
    def table(self) -> str:
        match self:
            case EntityType.MESSAGE:
                return "messages"
            case EntityType.ALERT:
                return "alerts"
            case EntityType.LOG_ENTRY:
                return "log_entries"
            case EntityType.USER:
                return "users"
            case EntityType.STORE:
                return "stores"

        raise ValueError(self)

    @property
    def cls(self) -> type[BaseEntity]:
        match self:
            case EntityType.MESSAGE:
                from ceres.message import Message

                return Message
            case EntityType.ALERT:
                from ceres.alert import Alert

                return Alert
            case EntityType.LOG_ENTRY:
                from ceres.logs import LogEntry

                return LogEntry
            case EntityType.USER:
                from ceres.user import User

                return User
            case EntityType.STORE:
                from ceres.store import Store

                return Store

        raise ValueError(self)
