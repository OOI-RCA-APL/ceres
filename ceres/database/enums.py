from ceres.data import StrEnum

__all__ = [
    "DatabaseType",
]


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"
