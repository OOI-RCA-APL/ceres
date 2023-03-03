from enum import Enum
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from pydantic import Field, validator

from ceres.address import Address
from ceres.data import DateTime, ImmutableDataObject, jsonify
from ceres.timing import utc


class AlertLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def priority(self) -> Any:
        return tuple(type(self)).index(self)

    def __lt__(self, __x: str) -> bool:
        if isinstance(__x, AlertLevel):
            return self.priority < __x.priority

        return super().__lt__(__x)

    def __le__(self, __x: str) -> bool:
        if isinstance(__x, AlertLevel):
            return self.priority <= __x.priority

        return super().__le__(__x)

    def __gt__(self, __x: str) -> bool:
        if isinstance(__x, AlertLevel):
            return self.priority > __x.priority

        return super().__gt__(__x)

    def __ge__(self, __x: str) -> bool:
        if isinstance(__x, AlertLevel):
            return self.priority >= __x.priority

        return super().__ge__(__x)


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    source: Address = cast(Address, None)
    timestamp: DateTime = Field(default_factory=utc)
    level: AlertLevel
    code: str
    info: Mapping[str, Any] = Field(default_factory=dict)

    @validator("info")
    def _validate_info(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            jsonify(value)
        except Exception:
            raise ValueError("info must be a JSON serializable mapping")

        return value
