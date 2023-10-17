from ceres.internal.utilities import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"


class DataType(StrEnum):
    COMPONENTS = "components"
    MESSAGES = "messages"
    ALERTS = "alerts"
    LOGS = "logs"

    @property
    def table(self) -> str:
        if self == DataType.LOGS:
            return "log_entries"

        return self.value
