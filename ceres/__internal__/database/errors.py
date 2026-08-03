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
# Every backend's wording for a row pointing at something that is not there. This is an
# integrity failure rather than a duplicate, so it is matched separately and never carries
# a column, the offending value being the reference rather than the row.
_FOREIGN_KEY_ERROR_REGEX = re.compile(
    r"FOREIGN KEY constraint failed|violates foreign key constraint",
)


@contextmanager
def wrap_database_errors() -> Iterator[None]:
    """Translate a driver failure into the Ceres error that describes it.

    The native store reports a driver failure as a plain value error carrying the driver's
    own words, so the wording is what decides here rather than the exception's class. That
    makes one constraint violation translate the same whichever backend surfaced it. A
    message no backend's wording recognizes belongs to whoever raised it and travels on
    unchanged.

    Yields:
        Control to the caller's block.

    Raises:
        AlreadyExistsError: If a unique constraint is violated.
        IntegrityError: If another integrity constraint is violated.
    """
    from ceres.error import IntegrityError

    try:
        yield
    except ValueError as exception:
        message = str(exception)
        _raise_if_already_exists(message)
        if _FOREIGN_KEY_ERROR_REGEX.search(message) is not None:
            raise IntegrityError()

        raise


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
