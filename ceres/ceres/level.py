from enum import Enum
from typing import Any


class Level(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def priority(self) -> Any:
        return tuple(type(self)).index(self)

    def __lt__(self, __x: str) -> bool:
        if isinstance(__x, Level):
            return self.priority < __x.priority

        return super().__lt__(__x)

    def __le__(self, __x: str) -> bool:
        if isinstance(__x, Level):
            return self.priority <= __x.priority

        return super().__le__(__x)

    def __gt__(self, __x: str) -> bool:
        if isinstance(__x, Level):
            return self.priority > __x.priority

        return super().__gt__(__x)

    def __ge__(self, __x: str) -> bool:
        if isinstance(__x, Level):
            return self.priority >= __x.priority

        return super().__ge__(__x)
