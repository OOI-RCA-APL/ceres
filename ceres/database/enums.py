from ceres.data import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
