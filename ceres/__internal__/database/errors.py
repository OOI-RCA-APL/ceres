import re
from collections.abc import Iterator
from contextlib import contextmanager

_SQLITE_UNIQUE_ERROR_REGEX = re.compile(
    r"UNIQUE constraint failed: (.+?)\.(?P<column>.+?)",
    re.MULTILINE | re.DOTALL,
)
_POSTGRES_UNIQUE_ERROR_REGEX = re.compile(
    r".*duplicate key.*\((?P<column>.+?)\)=\((?P<value>.+?)\)",
    re.MULTILINE | re.DOTALL,
)


@contextmanager
def wrap_database_errors() -> Iterator[None]:
    """Catch SQLAlchemy exceptions and re-raise them as Ceres domain errors.

    Translate integrity constraint violations into ``AlreadyExistsError`` or ``IntegrityError``,
    timeout errors into ``DatabaseUnreachableError``, programming errors into
    ``DatabaseProgrammingError``, and all other SQLAlchemy errors into
    ``DatabaseUnexpectedError``.

    Yields:
        Control to the caller's block. Any ``SQLAlchemyError`` raised inside the block is caught
        and translated.

    Raises:
        AlreadyExistsError: If a unique constraint is violated.
        IntegrityError: If another integrity constraint is violated.
        DatabaseUnreachableError: If a timeout occurs.
        DatabaseProgrammingError: If a programming error occurs.
        DatabaseUnexpectedError: For all other SQLAlchemy errors.
    """

    from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
    from sqlalchemy.exc import SQLAlchemyError

    from ceres.error import (
        AlreadyExistsError,
        DatabaseProgrammingError,
        DatabaseUnexpectedError,
        DatabaseUnreachableError,
        IntegrityError,
    )

    try:
        yield
    except SQLAlchemyError as exception:
        try:
            from sqlalchemy.dialects.postgresql.asyncpg import AsyncAdapt_asyncpg_dbapi

            PostgresIntegrityError = AsyncAdapt_asyncpg_dbapi.IntegrityError
        except ImportError:
            PostgresIntegrityError = None

        from sqlite3 import IntegrityError as SQLiteIntegrityError

        import sqlalchemy.exc

        if isinstance(
            exception,
            sqlalchemy.exc.ArgumentError | sqlalchemy.exc.InvalidRequestError,
        ):
            from ceres.error import trace

            raise DatabaseProgrammingError(exception=trace(exception))

        if isinstance(exception, sqlalchemy.exc.TimeoutError):
            raise DatabaseUnreachableError(reason=str(exception))

        if isinstance(exception, SQLAlchemyIntegrityError):
            if isinstance(exception.orig, SQLiteIntegrityError):
                match = _SQLITE_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise AlreadyExistsError(field=match.group("column"))
            elif PostgresIntegrityError is not None and isinstance(
                exception.orig, PostgresIntegrityError
            ):
                match = _POSTGRES_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise AlreadyExistsError(
                        field=match.group("column"),
                        value=match.group("value"),
                    )

            raise IntegrityError()

        raise DatabaseUnexpectedError(reason=str(exception))
