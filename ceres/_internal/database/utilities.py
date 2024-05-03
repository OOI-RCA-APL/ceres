import re
from contextlib import contextmanager
from sqlite3 import IntegrityError as SQLiteIntegrityError
from typing import Iterator

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ceres.errors import AlreadyExistsError, DatabaseUnexpectedError, Failure

_SQLITE_UNIQUE_ERROR_REGEX = re.compile(
    r"UNIQUE constraint failed: ([^ ]+)\.(?P<column>[^ ]+)",
    re.MULTILINE | re.DOTALL,
)
_POSTGRES_UNIQUE_ERROR_REGEX = re.compile(
    r".*duplicate key.*\((?P<column>[^ ]+)\)=",
    re.MULTILINE | re.DOTALL,
)


@contextmanager
def wrap_database_errors() -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError as exception:
        try:
            from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi

            PostgresIntegrityError = AsyncAdapt_asyncpg_dbapi.IntegrityError
        except ImportError:
            PostgresIntegrityError = None

        if isinstance(exception, IntegrityError):
            if isinstance(exception.orig, SQLiteIntegrityError):
                match = _SQLITE_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(AlreadyExistsError(field=match.group("column")))
            elif PostgresIntegrityError is not None and isinstance(
                exception.orig, PostgresIntegrityError
            ):
                match = _POSTGRES_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(AlreadyExistsError(field=match.group("column")))

        raise Failure(DatabaseUnexpectedError(message=str(exception)))
