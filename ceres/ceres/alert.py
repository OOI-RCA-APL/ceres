from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field

from .data import ImmutableDataObject
from .datetime import utc


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class Alert(ImmutableDataObject):
    id: UUID = Field(default_factory=uuid4)
    component_id: UUID = UUID(int=0)
    timestamp: datetime = Field(default_factory=utc)
    level: AlertLevel
    code: str
    info: dict[str, Any] = Field(default_factory=dict)
