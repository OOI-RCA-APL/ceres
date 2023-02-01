from datetime import datetime
from enum import Enum
from typing import Any, Mapping, cast
from uuid import UUID, uuid4

from pydantic import Field, validator

from .address import ComponentAddress
from .data import ImmutableDataObject, jsonify
from .datetime import utc


class AlertLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    source: ComponentAddress = cast(ComponentAddress, None)
    timestamp: datetime = Field(default_factory=utc)
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
