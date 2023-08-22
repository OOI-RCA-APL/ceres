from enum import Enum


class DataFormat(str, Enum):
    CSV = "csv"
    SQLITE = "sqlite"


class TableOption(str, Enum):
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
