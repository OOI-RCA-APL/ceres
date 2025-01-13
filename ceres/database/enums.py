from __future__ import annotations

from ceres.data import StrEnum


class DatabaseType(StrEnum):
    SQLITE = "sqlite"
    POSTGRES = "postgres"


class DataFormat(StrEnum):
    CSV = "csv"
    SQLITE = "sqlite"
