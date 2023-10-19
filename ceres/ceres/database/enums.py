from ceres.internal.utilities import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"


class ItemType(StrEnum):
    STORE = "store"
    MESSAGE = "message"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"

    @property
    def table(self) -> str:
        match self:
            case ItemType.STORE:
                return "stores"
            case ItemType.MESSAGE:
                return "messages"
            case ItemType.ALERT:
                return "alerts"
            case ItemType.LOG_ENTRY:
                return "log_entries"

        raise ValueError(self)
