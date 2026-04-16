import logging
from types import MappingProxyType
from typing import Final

from ceres.data import OrderedStrEnum

__all__ = [
    "Level",
]


class Level(OrderedStrEnum):
    """Severity levels used throughout Ceres for events, alerts, and logs.

    Levels are ordered from least to most severe, so comparisons like `level >= Level.WARNING`
    behave as expected. The string values match the lowercase names of the standard `logging`
    module levels.
    """

    DEBUG = "debug"
    """Detailed diagnostic information, typically only enabled when troubleshooting."""

    INFO = "info"
    """Routine operational messages confirming things are working as expected."""

    WARNING = "warning"
    """Something unexpected occurred, or a problem may occur in the near future."""

    ERROR = "error"
    """A serious problem occurred, the operation failed."""

    CRITICAL = "critical"
    """A very serious error, the program may be unable to continue running."""

    def to_int(self) -> int:
        """Convert this level to its corresponding integer value from the `logging` module.

        Returns:
            The integer constant from the standard `logging` module that corresponds to this
            severity level.
        """
        return _LEVEL_TO_INT[self]

    @classmethod
    def from_int(cls, value: int, /) -> Level:
        """Convert an integer `logging` module level to a `Level`.

        Args:
            value: An integer matching one of the standard `logging` module level constants
                (e.g. `logging.WARNING`).

        Returns:
            The `Level` member corresponding to the given integer.

        Raises:
            TypeError: If `value` is not an integer.
            ValueError: If `value` does not match any known log level.
        """
        if not isinstance(value, int):
            raise TypeError(f"Value {value!r} is not an integer.")

        try:
            return _INT_TO_LEVEL[value]
        except KeyError:
            raise ValueError(f"Value {value!r} is not associated with a known log level.") from None


_LEVEL_TO_INT: Final = MappingProxyType(
    {
        Level.DEBUG: logging.DEBUG,
        Level.INFO: logging.INFO,
        Level.WARNING: logging.WARNING,
        Level.ERROR: logging.ERROR,
        Level.CRITICAL: logging.CRITICAL,
    }
)

_INT_TO_LEVEL: Final = MappingProxyType({value: key for key, value in _LEVEL_TO_INT.items()})
