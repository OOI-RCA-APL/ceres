from ceres.data import StrEnum

__all__ = [
    "DatabaseType",
]


class DatabaseType(StrEnum):
    """Kind of database backend Ceres is running against."""

    SQLITE = "sqlite"
    """Local SQLite database, the default for single-node deployments."""
    POSTGRES = "postgres"
    """PostgreSQL server, used for shared and production deployments."""
    TURSO = "turso"
    """Local Turso database, a SQLite-compatible backend that allows concurrent writers."""
