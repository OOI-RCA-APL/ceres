from typing import List

from .adapter import DatabaseAdapter


class SQLiteDatabaseAdapter(DatabaseAdapter):
    @property
    def ddl(self) -> List[str]:
        return [
            """
            CREATE TABLE unit (
                id TEXT NOT NULL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL
            ) STRICT;
            """,
            """
            CREATE TABLE connection (
                id TEXT NOT NULL PRIMARY KEY,
                unit_id TEXT NOT NULL REFERENCES unit,
                name text NOT NULL
            ) STRICT;
            """,
            """
            CREATE UNIQUE INDEX uk_connection__id__unit_id ON connection (id, unit_id);
            """,
            """
            CREATE TABLE message (
                id TEXT NOT NULL PRIMARY KEY,
                connection_id TEXT NOT NULL REFERENCES connection,
                timestamp TEXT NOT NULL,
                direction TEXT NOT NULL,
                content TEXT NOT NULL,
                CHECK (direction in ('send', 'receive'))
            ) STRICT;
            """,
            """
            CREATE INDEX ix_message__connection_id ON message (connection_id);
            """,
            """
            CREATE INDEX ix_message__timestamp ON message (timestamp);
            """,
            """
            CREATE INDEX ix_message__content ON message (content);
            """,
        ]

    @property
    def tables(str) -> str:
        return """
            SELECT name FROM sqlite_schema
            WHERE type='table'
            ORDER BY name
            """
