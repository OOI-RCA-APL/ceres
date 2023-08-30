from abc import abstractmethod
from os import PathLike
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema, core_schema
from sqlalchemy import URL, make_url
from sqlalchemy.exc import ArgumentError
from typing_extensions import Self, override

from ceres.database.enums import DatabaseType


class BaseDatabaseURL:
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        source_type: Any,
        handler: GetCoreSchemaHandler,
    ) -> CoreSchema:
        return core_schema.no_info_after_validator_function(
            cls, handler(Any), serialization=core_schema.to_string_ser_schema()
        )

    def __get_pydantic_json_schema__(
        self,
        core_schema: CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        json_schema["type"] = "string"
        return json_schema

    def __init__(self, value: str, /) -> None:
        self._value = value
        try:
            self._parsed = make_url(value)
        except ArgumentError as exception:
            raise ValueError("invalid database URL") from exception

    def __str__(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._value!r})"

    @property
    @abstractmethod
    def type(self) -> DatabaseType:
        ...

    @property
    def scheme(self) -> str:
        return self._parsed.drivername

    @property
    def query(self) -> Mapping[str, tuple[str, ...] | str]:
        return self._parsed.query


SQLiteScheme = Literal["sqlite"]


class SQLiteURL(BaseDatabaseURL):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        if self._parsed.drivername != "sqlite":
            raise ValueError("scheme for SQLite must be 'sqlite'")
        if self._parsed.database is None:
            raise ValueError("database path is required")

        self.__path = Path(self._parsed.database)

    @property
    @override
    def type(self) -> Literal[DatabaseType.SQLITE]:
        return DatabaseType.SQLITE

    @property
    def path(self) -> Path:
        return self.__path

    @classmethod
    def create(cls, *, path: str | PathLike[str]) -> Self:
        return cls(str(URL.create(drivername="sqlite", database=str(path))))


PostgresScheme = Literal["postgres", "postgresql"]


class PostgresURL(BaseDatabaseURL):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        if self._parsed.drivername not in ("postgres", "postgresql"):
            raise ValueError("scheme must be 'postgres' or 'postgresql'")
        if self._parsed.host is None:
            raise ValueError("host is required")

    @property
    @override
    def type(self) -> Literal[DatabaseType.POSTGRES]:
        return DatabaseType.POSTGRES

    @property
    def host(self) -> str:
        assert self._parsed.host is not None
        return self._parsed.host

    @property
    def port(self) -> int | None:
        return self._parsed.port

    @property
    def username(self) -> str | None:
        return self._parsed.username

    @property
    def password(self) -> str | None:
        return self._parsed.password

    @property
    def database(self) -> str | None:
        return self._parsed.database

    @classmethod
    def create(
        cls,
        *,
        scheme: Literal["postgres", "postgresql"] = "postgres",
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> Self:
        return cls(
            str(
                URL.create(
                    drivername=scheme,
                    host=host,
                    port=port,
                    username=username,
                    password=password,
                    database=database,
                )
            )
        )


DatabaseURL = SQLiteURL | PostgresURL
