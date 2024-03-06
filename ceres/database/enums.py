from ceres.data import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"


class ItemType(StrEnum):
    MESSAGE = "message"
    ALERT = "alert"
    LOG_ENTRY = "log-entry"
    STORE = "store"

    @property
    def table(self) -> str:
        match self:
            case ItemType.MESSAGE:
                return "messages"
            case ItemType.ALERT:
                return "alerts"
            case ItemType.LOG_ENTRY:
                return "log_entries"
            case ItemType.STORE:
                return "stores"

        raise ValueError(self)
