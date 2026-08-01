import re
from collections.abc import Iterator
from contextlib import contextmanager

# SQLite and Turso both name the constraint's columns as "table.column", listing them comma
# separated when more than one column makes up the constraint, and Turso appends its result code
# in parentheses. The first column is the one reported, so the capture stops at the first comma or
# space rather than running to the end of the message.
_SQLITE_UNIQUE_ERROR_REGEX = re.compile(
    r"UNIQUE constraint failed: [^.]+\.(?P<column>[^,\s]+)",
)
# PostgreSQL puts the column and the value that collided in the detail line, as
# "Key (username)=(taken) already exists".
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
        DatabaseProgrammingError,
        DatabaseUnexpectedError,
        DatabaseUnreachableError,
        IntegrityError,
    )

    try:
        yield
    except SQLAlchemyError as exception:
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
            _raise_if_already_exists(str(exception.orig))
            raise IntegrityError()

        raise DatabaseUnexpectedError(reason=str(exception))


def _raise_if_already_exists(message: str) -> None:
    """Raise `AlreadyExistsError` when `message` reports a unique constraint violation.

    Each backend words the violation its own way, so the wording is what decides rather than
    which driver raised it. Turso and the SQLite driver report the same text through different
    exception classes, and a driver that reports neither wording falls through to the caller's
    plain integrity error.
    """
    from ceres.error import AlreadyExistsError

    match = _SQLITE_UNIQUE_ERROR_REGEX.search(message)
    if match is not None:
        raise AlreadyExistsError(field=match.group("column"))

    match = _POSTGRES_UNIQUE_ERROR_REGEX.match(message)
    if match is not None:
        raise AlreadyExistsError(field=match.group("column"), value=match.group("value"))
