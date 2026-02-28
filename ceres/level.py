import logging
from types import MappingProxyType
from typing import Final

from ceres.data import OrderedStrEnum

__all__ = [
    "Level",
]


class Level(OrderedStrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    def to_int(self) -> int:
        return _LEVEL_TO_INT[self]

    @classmethod
    def from_int(cls, value: int, /) -> Level:
        if not isinstance(value, int):
            raise TypeError(f"Value {value!r} is not an integer.")

        try:
            return _INT_TO_LEVEL[value]
        except KeyError:
            raise ValueError(f"Value {value!r} is not associated with a known log level.")


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
