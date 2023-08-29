from ceres.internal.utilities import StrEnum


class DatabaseKind(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"


class TableOption(StrEnum):
    ALL = "all"
    COMPONENTS = "components"
    MESSAGES = "messages"
    ALERTS = "alerts"
    LOG_ENTRIES = "log-entries"

    @property
    def table_name(self) -> str:
        if self == TableOption.LOG_ENTRIES:
            return "log_entries"

        return self.value
