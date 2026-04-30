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
    ``DatabaseUnexpectedError``. Every translated error is wrapped in a ``Failure`` exception.

    Yields:
        Control to the caller's block. Any ``SQLAlchemyError`` raised inside the block is caught
        and translated.

    Raises:
        Failure: Always raised when a SQLAlchemy error occurs, wrapping the appropriate Ceres
            domain error.
    """

    from sqlalchemy.exc import IntegrityError as SQLAlchemyIntegrityError
    from sqlalchemy.exc import SQLAlchemyError

    from ceres.error import (
        AlreadyExistsError,
        DatabaseProgrammingError,
        DatabaseUnexpectedError,
        DatabaseUnreachableError,
        Failure,
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

            raise Failure(DatabaseProgrammingError(exception=trace(exception)))

        if isinstance(exception, sqlalchemy.exc.TimeoutError):
            raise Failure(DatabaseUnreachableError(reason=str(exception)))

        if isinstance(exception, SQLAlchemyIntegrityError):
            if isinstance(exception.orig, SQLiteIntegrityError):
                match = _SQLITE_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(AlreadyExistsError(field=match.group("column")))
            elif PostgresIntegrityError is not None and isinstance(
                exception.orig, PostgresIntegrityError
            ):
                match = _POSTGRES_UNIQUE_ERROR_REGEX.match(str(exception.orig))
                if match is not None:
                    raise Failure(
                        AlreadyExistsError(
                            field=match.group("column"),
                            value=match.group("value"),
                        )
                    )

            raise Failure(IntegrityError)

        raise Failure(DatabaseUnexpectedError(reason=str(exception)))
